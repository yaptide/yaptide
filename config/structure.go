package config

// Config contains basic server configuration
type Config struct {
	BackendPublicUrl string
	BackendPort      int64
	DbUrl            string
}
