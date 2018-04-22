package web

import (
	"context"

	"github.com/yaptide/yaptide/model"
)

type userLoginResponse struct {
	Token string      `json:"token"`
	User  *model.User `json:"user"`
}

func (h *handler) userGetHandler(
	ctx context.Context,
) (*model.User, error) {
	db := extractDBSession(ctx)
	userID := extractUserID(ctx)

	user, userErr := h.Resolver.UserGet(db, userID)
	if userErr != nil {
		return nil, userErr
	}
	return user, nil
}

func (h *handler) userLoginHandler(
	ctx context.Context, input *model.UserLoginInput,
) (*userLoginResponse, error) {
	db := extractDBSession(ctx)

	token, user, loginErr := h.Resolver.UserLogin(db, input)
	if loginErr != nil {
		return nil, loginErr
	}
	return &userLoginResponse{
		Token: token,
		User:  user,
	}, nil
}

func (h *handler) userRegisterHandler(
	ctx context.Context, form *model.UserRegisterInput,
) (*model.User, error) {
	db := extractDBSession(ctx)
	log.Debug("Register request")
	user, registerErr := h.Resolver.UserRegister(db, form)
	if registerErr != nil {
		return nil, registerErr
	}
	return user, nil
}
