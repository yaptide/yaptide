from flask import request
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import PlgridUserModel, AuthProvider

from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response


class AuthPlgrid(Resource):
    """Class responsible for user log in"""

    @staticmethod
    def post():
        """Method returning status of logging in (and token if it was successful)"""
        plgrid_token: dict = request.headers.get('Plgrid_token', None)
        if plgrid_token is None:
            return yaptide_response(message='No plgrid token provided', code=401)
        
        # TODO: aquire certificate from plgrid here and save it in db

        username = plgrid_token["tokenParsed"]["preferred_username"]
        
        user = db.session.query(PlgridUserModel).filter_by(username=username).first()
        if not user:
            user = PlgridUserModel(username=username,
                                   auth_provider=AuthProvider.PLGRID.value,
                                   certificate="")

            db.session.add(user)
            db.session.commit()

        exp = plgrid_token["tokenParsed"]["exp"]

        try:
            access_token, access_exp = encode_auth_token(user_id=user.id,
                                                         is_refresh=False,
                                                         exp_time=exp)
            refresh_token, refresh_exp = encode_auth_token(user_id=user.id,
                                                           is_refresh=True,
                                                           exp_time=exp)

            resp = yaptide_response(
                message='Successfully logged in',
                code=202,
                content={
                    'access_exp': int(access_exp.timestamp()*1000),
                    'refresh_exp': int(refresh_exp.timestamp()*1000),
                }
            )
            resp.set_cookie('access_token', access_token, httponly=True, samesite='Lax', expires=access_exp)
            resp.set_cookie('refresh_token', refresh_token, httponly=True, samesite='Lax', expires=refresh_exp)
            return resp
        except Exception:  # skipcq: PYL-W0703
            return error_internal_response()
    
    @staticmethod
    def delete():
        """Method returning status of logging out"""
        resp = yaptide_response(message='User logged out', code=200)
        resp.delete_cookie('access_token')
        resp.delete_cookie('refresh_token')
        return resp
