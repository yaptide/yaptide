package web

import (
	"context"

	"github.com/yaptide/app/model"
)

type userLoginResponse struct {
	Token string
	User  *model.User
}

func (h *handler) userGetHandler(
	ctx context.Context,
) (*model.User, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)

	user, userErr := h.Resolver.UserGet(db, userID)
	if userErr != nil {
		return nil, userErr
	}
	return user, nil
}

func (h *handler) userLoginHandler(
	input *model.UserLoginInput, ctx context.Context,
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
	form *model.UserRegisterInput, ctx context.Context,
) (*model.User, error) {
	db := extractDBSession(ctx)

	user, registerErr := h.Resolver.UserRegister(db, form)
	if registerErr != nil {
		return nil, registerErr
	}
	return user, nil
}
