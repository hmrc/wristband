from flask import Flask
from flask_restful import Resource, Api

app = Flask(__name__)
api = Api(app)

class Ping(Resource):
    def get(self):
        return {'status': 'OK'}

api.add_resource(Ping, '/ping/ping')

if __name__ == '__main__':
    import os
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
