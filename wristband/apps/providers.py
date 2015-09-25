import datetime
import requests
from concurrent import futures
from django.conf import settings
from ..providers import providers_config

from wristband.common.utils import extract_stage, extract_security_zone_from_env
from wristband.providers.generics import JsonDataProvider
from wristband.providers.models import Job

EXPIRY_JOB_TIME_MINUTES = 10


class ParentReleaseAppDataProvider(JsonDataProvider):
    def _get_raw_data(self):
        url = settings.RELEASES_APP_URI
        response = requests.get(url)
        return response.json()

    @staticmethod
    def extract_stage_from_env(env):
        return extract_stage(env)

    @staticmethod
    def extract_security_zone_from_env(env):
        return extract_security_zone_from_env(env)

    def to_models(self):
        pass


class NestedReleaseAppDataProvider(ParentReleaseAppDataProvider):
    def _get_list_data(self):
        """
        Show only the latest version per stage, filter by last seen
        """
        data = [{'name': app['an'],
                 'version': app['ver'],
                 'stage': self.extract_stage_from_env(app['env'])}
                for app in self.raw_data]
        return sorted(data, key=lambda x: x['name'])

    def get_filtered_list_data(self, pk, domain_pk):
        filtered_apps = filter(lambda x: x[domain_pk] == pk, self.list_data)
        return sorted(filtered_apps, key=lambda x: x['name'])

    def to_models(self):
        ordered_data = sorted(self.raw_data, key=lambda x: x['ls'], reverse=True)
        return [{'name': app['an'],
                 'stage': self.extract_stage_from_env(app['env']),
                 'security_zone': self.extract_security_zone_from_env(app['env'])}
                for app in ordered_data]


class ReleaseAppDataProvider(ParentReleaseAppDataProvider):
    _not_expired_jobs = None

    def get_not_expired_jobs(self):
        if self._not_expired_jobs is None:
            time_delta = datetime.datetime.now() - datetime.timedelta(minutes=EXPIRY_JOB_TIME_MINUTES)
            self._not_expired_jobs = Job.objects(start_time__gte=time_delta).ordered_by_time(desc=True) # this is a list!
        return self._not_expired_jobs

    def get_last_job_id_per_app(self, app_name, stage):
        try:
            return filter(lambda x: x.app.name == app_name and x.app.stage == stage, self.get_not_expired_jobs())[0].id
        except IndexError:
            return None

    def _get_list_data(self):
        """
        We need to get this format from the current releases app format
        Releases app also returns some history, so we need to sort by last seen first.
        A relational database would simplify this code because this is nasty and slow


        Releases app output:
        [
            {
                "an": "a-b-test",
                "env": "qa-left",
                "ver": "1.7.7"
            },
            {
                "an": "a-b-test",
                "env": "staging-left",
                "ver": "1.7.2"
            }
        ]

        Expected output:
        [
            {
                "name": "a-b-test",
                    "stages": [
                        {
                           "name": "qa",
                           "version": "1.7.7"
                           "job_id": "434532424"
                        },
                        {
                           "name": "staging",
                           "version": "1.7.2"
                           "job_id": None
                        }
                    ]
            },
            {...}
        ]
        """
        data = []
        # this assumes that last seen corresponds to the latest version
        ordered_data = sorted(self.raw_data, key=lambda x: x['ls'], reverse=True)
        apps_indexes = {}
        for app in ordered_data:
            app_name = app['an']
            app_stage = extract_stage(app['env'])
            if app_name in apps_indexes.keys():
                # we've already seen this app
                # check if we already have the relevant stage,
                # the data has been ordered, if we have this stage then we should already have the latest one

                already_seen_app_index = apps_indexes[app_name]
                app_stages_names = [stage['name'] for stage in data[already_seen_app_index]['stages']]
                if app_stage not in app_stages_names:
                    # we don't have this stage at all, just add it
                    data[already_seen_app_index]['stages'].append({
                        'name': app_stage,
                        'version': app['ver'],
                        'job_id': self.get_last_job_id_per_app(app_name, app_stage)
                    })
            else:
                # this is the best case
                # we've never seen this app before, just add the app and the stage+version
                app_to_be_added = {
                    'name': app_name,
                    'stages': [{
                        'name': app_stage,
                        'version': app['ver'],
                        'job_id': self.get_last_job_id_per_app(app_name, app_stage)
                    }]
                }
                data.append(app_to_be_added)
                apps_indexes[app_name] = len(data) - 1
        return sorted(data, key=lambda x: x['name'])


class DocktorAppDataProvider(ReleaseAppDataProvider):
    _not_expired_jobs = None

    def _get_raw_data(self):
        session = requests.Session()
        apps = []
        for stage in providers_config.providers['docktor'].keys():
            for zone in providers_config.providers['docktor'][stage].keys():
                config = providers_config.providers['docktor'][stage][zone]
                URLS = ["{}/apps/{}".format(config["uri"], a) for a in session.get("{}/apps/".format(config["uri"])).json()]
                with futures.ThreadPoolExecutor(max_workers=30) as executor:
                    future_to_url = (executor.submit(requests.get, url) for url in URLS)
                    for future in futures.as_completed(future_to_url):
                        data = future.result().json()
                        now = (datetime.datetime.now() - datetime.datetime(1970,1,1)).total_seconds()
                        apps.append({
                            "fs": now,
                            "ls": now,
                            "an": data["app"],
                            "env": "{}-{}".format(stage, zone),
                            "ver": data["slug_uri"].split("_")[1].rstrip(".tgz")
                        })
        return apps
