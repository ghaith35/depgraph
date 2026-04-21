package main

import (
	"fmt"
	"github.com/example/myapp/internal/auth"
)

func main() {
	fmt.Println(auth.Login("user"))
}
