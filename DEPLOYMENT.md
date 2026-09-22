# Deployment

The `main` branch deploys to the private Drop Rate Railway development service.

Health checks:

- `/health/live` confirms the API process is running.
- `/health/ready` confirms the restricted PostgreSQL connection is available.
