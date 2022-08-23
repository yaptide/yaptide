from typing import Union
from flask import make_response, Response


def yaptide_response(message: str, code: int, content: Union[dict, str] = "") -> Response:
    """Function returning Response object"""
    response_dict = {'message': message}
    if type(content) is dict:
        for key in content:
            response_dict[key] = content[key]
    return make_response(response_dict, code)


def error_validation_response() -> Response:
    """Function returning Response object when ValidationError occures"""
    return yaptide_response(message='Wrong data provided', code=400)


def error_internal_response() -> Response:
    """Function returning Response object when Exception occures"""
    return yaptide_response(message='Internal server error', code=500)
