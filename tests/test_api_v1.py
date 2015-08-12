from flask import json, url_for
from flask.ext.restful import Resource
import mock
import pytest

ALL_PIPELINES_MOCK = mock.Mock(return_value={
    "zone_one": ["qa-zone_one", "staging-zone_one"],
    "zone_two": ["qa-zone_two", "staging-zone_two"],
})

ALL_ENVIRONMENTS_MOCK = mock.Mock(return_value=[
    "qa-zone_one",
    "qa-zone_two",
    "staging-zone_one",
    "staging-zone_two"
])

V1_MOCKS = {
    'jenkins': mock.patch('api.v1.Jenkins', spec=True),
    'all_releases': mock.patch('api.v1.get_all_releases'),
    'all_pipelines': mock.patch('api.v1.get_all_pipelines', new=ALL_PIPELINES_MOCK),
    'all_environments': mock.patch('api.v1.get_all_environments', new=ALL_ENVIRONMENTS_MOCK)
}


def apply_mocks(*args):
    def _decorator(func):
        for m in args:
            func = V1_MOCKS[m](func)
        return func

    return _decorator


@apply_mocks('all_releases', 'all_pipelines')
def test_promote_fails_if_not_deployed_to_previous_environment(all_releases_mock, client):
    all_releases_mock.return_value = [
        {
            "app_name": "another-app",
            "environment": "qa",
            "last_seen": 10,
            "version": "0.0.3"
        }
    ]
    url = url_for('api_v1.promotion', deploy_env='staging-zone_one', app_name='my-app', app_version='0.0.8')
    resource = client.get(url)
    assert resource.status_code == 400
    assert json.loads(resource.data) == {"error": "you need to deploy 0.0.8 to qa-zone_one first"}


@apply_mocks('all_releases', 'all_pipelines', 'all_environments')
def test_api_config_endpoint(all_releases_mock, client):
    all_releases_mock.return_value = [
        {
            "app_name": "app-1",
            "environment": "staging-zone_one",
            "last_seen": 18,
            "version": "0.4.3"
        },
        {
            "app_name": "app-2",
            "environment": "staging-zone_two",
            "last_seen": 10,
            "version": "0.0.3"
        }
    ]
    resource = client.get(url_for('api_v1.config'))
    assert 'apps' in resource.data
    assert 'envs' in resource.data
    assert 'pipelines' in resource.data


@mock.patch('api.v1.session', new_callable=dict)
@mock.patch('api.v1.get_jenkins_uri')
@apply_mocks('all_releases', 'jenkins', 'all_pipelines')
def test_promote_sse_stream(all_releases_mock, jenkins_mock, get_jenkins_uri_mock,  mocked_session, client):
    JENKINS_URL = 'https://username:pass@staging-zone_one'
    all_releases_mock.return_value = [
        {
            "app_name": "my-app",
            "environment": "qa-zone_one",
            "last_seen": 10,
            "version": "0.0.8"
        }
    ]
    get_jenkins_uri_mock.return_value = JENKINS_URL
    mocked_session.update({'username': 'test_username'})

    expected_response = "".join([
        'event: queued\ndata: {"status": "OK"}\n\n',
        'event: building\ndata: {"status": "OK"}\n\n',
        'event: success\ndata: {"status": "OK"}\n\n'
    ])

    url = url_for('api_v1.promotion', deploy_env='staging-zone_one', app_name='my-app', app_version='0.0.8')
    resource = client.get(url)
    assert resource.is_streamed
    assert resource.content_type == 'text/event-stream'
    assert resource.data == expected_response
    jenkins_mock.assert_has_calls([mock.call(
        JENKINS_URL.replace("username:pass@", ""),
        username="username", password="pass")], any_order=True)


@mock.patch('api.v1.ldap_authentication')
@mock.patch('api.v1.session', new_callable=dict)
def test_login_successful(mocked_session, mocked_ldap_authentication, client):
    """
    For what we care in this test the session behaves like a dictionary
    Session is then replaced with a dictionary for easy testing
    """
    mocked_ldap_authentication.return_value = True
    url = url_for('api_v1.login')
    resource = client.post(url, data={'username': 'username', 'password': 'password'})
    assert json.loads(resource.data) == {'status': 'Authorised'}
    assert resource.status_code == 200
    assert mocked_session['authenticated'] is True
    assert mocked_session['username'] == 'username'


@mock.patch('api.v1.ldap_authentication')
@mock.patch('api.v1.session', new_callable=dict)
def test_login_failed(mocked_session, mocked_ldap_authentication, client):
    """
    For what we care in this test the session behaves like a dictionary
    Session is then replaced with a dictionary for easy testing
    """
    mocked_ldap_authentication.return_value = False
    url = url_for('api_v1.login')
    resource = client.post(url, data={'username': 'username', 'password': 'password'})
    assert json.loads(resource.data) == {'status': 'Unauthorised'}
    assert resource.status_code == 401
    assert 'authenticated' not in mocked_session
    assert 'username' not in mocked_session


@pytest.mark.parametrize(('mocked_session', ), [
    (
        {'authenticated': True, 'username': 'test_username'},
    ),
    (
        {},
    )
])
def test_logout(mocked_session, client):
    with mock.patch('api.v1.session', new_callable=dict) as ms:
        ms.update(mocked_session)
        url = url_for('api_v1.logout')
        resource = client.get(url)
        assert 'authenticated' not in ms
        assert 'username' not in ms
        assert json.loads(resource.data) == {'status': 'OK'}
        assert resource.status_code == 200