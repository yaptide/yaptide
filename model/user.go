package model

import (
	"fmt"

	"golang.org/x/crypto/bcrypt"
	"gopkg.in/mgo.v2/bson"
)

// User contains account login data.
type User struct {
	ID           bson.ObjectId `json:"id,omitempty" bson:"_id,omitempty"`
	Username     string        `json:"username" bson:"username"`
	Email        string        `json:"email" bson:"email"`
	PasswordHash string        `json:"-" bson:"password"`
}

type UserLoginInput struct {
	Username string
	Password string
}

func (u UserLoginInput) Validate() error {
	if u.Username == "" {
		return fmt.Errorf("Username can't be empty")
	}
	if u.Password == "" {
		return fmt.Errorf("Password can't be empty")
	}
	if len(u.Password) < 8 {
		return fmt.Errorf("Password is to short, you need at least 8 characters")
	}
	return nil
}

func (u UserLoginInput) ValidatePassword(hashedPassword string) error {
	err := bcrypt.CompareHashAndPassword([]byte(hashedPassword), []byte(u.Password))
	if err != nil {
		return fmt.Errorf("Unknown combination of user and password")
	}
	return nil
}

type UserRegisterInput struct {
	Email    string `json:"email"`
	Username string `json:"username"`
	Password string `json:"password"`
}

func (u UserRegisterInput) Validate() error {
	if u.Username == "" {
		return fmt.Errorf("Username can't be empty")
	}
	if u.Password == "" {
		return fmt.Errorf("Password can't be empty")
	}
	if u.Email == "" {
		return fmt.Errorf("Email can't be empty")
	}
	if len(u.Password) < 8 {
		return fmt.Errorf("Password is to short, you need at least 8 characters")
	}
	return nil
}

func (u UserRegisterInput) ToUser() *User {
	return &User{
		ID:           bson.NewObjectId(),
		Username:     u.Username,
		Email:        u.Email,
		PasswordHash: u.generatePasswordHash(),
	}
}

func (u UserRegisterInput) generatePasswordHash() string {
	hashedPassword, err := bcrypt.GenerateFromPassword(
		[]byte(u.Password), bcrypt.DefaultCost,
	)
	if err != nil {
		log.Error("[ASSERT] Failed to hash password")
		panic(err)
	}
	return string(hashedPassword)
}
