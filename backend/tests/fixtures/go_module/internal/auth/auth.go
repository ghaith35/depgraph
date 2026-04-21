package auth

import "fmt"

func Login(user string) string {
	return fmt.Sprintf("logged in: %s", user)
}
