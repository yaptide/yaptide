# Copilot Instructions for yaptide

## Project Overview

Yaptide (Yet Another Particle Transport IDE) is a Flask-based backend application for particle transport simulations. The application uses:
- **Python 3.9-3.12** as the primary language
- **Flask** for the web framework
- **SQLAlchemy** with PostgreSQL for database
- **Celery** with Redis for task queue
- **Poetry** for dependency management
- **Docker** for containerization

User documentation: https://yaptide.github.io/docs/
Developer documentation: https://yaptide.github.io/for_developers/

## Project Structure

- `yaptide/` - Main application source code
  - `admin/` - Admin utilities including simulator downloads
  - `batch/` - Batch processing functionality
  - `celery/` - Celery task definitions
  - `persistence/` - Database models and ORM layer
  - `routes/` - Flask API routes
  - `utils/` - Utility functions
  - `application.py` - Flask app factory
  - `settings.py` - Application settings
- `tests/` - Test suite (pytest)
- `migrations/` - Database migrations (Flask-Migrate/Alembic)
- `scripts/` - Deployment and setup scripts
- `yaptide_tester/` - Testing utilities

## Coding Standards

### Python Style
- Follow **PEP 8** style guide
- Use **yapf** formatter with configuration in `pyproject.toml`:
  - Based on PEP 8 style
  - **120 character line limit**
  - Configuration: `[tool.yapf]` section in `pyproject.toml`
- All Python code should be formatted with yapf before committing

### Code Quality Tools
- **pre-commit hooks** are configured (`.pre-commit-config.yaml`):
  - trailing-whitespace removal
  - end-of-file-fixer
  - check-yaml and check-toml
  - check-added-large-files
  - yapf formatter
  - Custom hook: check_not_empty_env_files
- Run `pre-commit run --all-files` before committing
- Migrations directory is excluded from pre-commit checks

### Naming Conventions
- Use snake_case for functions, variables, and module names
- Use PascalCase for class names
- Use UPPER_CASE for constants
- Prefix private functions/methods with underscore `_`

### Documentation
- Use docstrings for all public functions, classes, and modules
- Follow Google-style docstrings format
- Include type hints where appropriate
- Keep comments clear and concise

## Testing

### Framework and Setup
- Use **pytest** as the testing framework
- Test files are located in the `tests/` directory
- Configuration in `pytest.ini`

### Test Environment
- Tests use in-memory broker and result backend for Celery: `memory://` and `cache+memory://`
- Tests use SQLite in-memory database: `sqlite://`
- Flask testing mode is enabled: `FLASK_TESTING=True`
- Live server runs on port 5000 for integration tests

### Running Tests
```bash
# Install test dependencies
poetry install --with test

# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_main.py

# Run with coverage
poetry run pytest --cov=yaptide
```

### Test Structure
- Tests should be in the `tests/` directory (configured in `pytest.ini`)
- Use fixtures defined in `conftest.py` for common setup
- Each test should be isolated and independent
- Integration tests are in `tests/integration/`

### Writing Tests
- Name test files with `test_` prefix
- Name test functions with `test_` prefix
- Use descriptive test names that explain what is being tested
- Use fixtures for app and client: `app` and `client` fixtures are available
- Create database tables in tests using `db.create_all()` and clean up with `db.drop_all()`

## Building and Running

### Local Development Setup
1. Install Poetry: https://python-poetry.org/docs/#installation
2. Install dependencies: `poetry install`
3. Run the application: Follow instructions at https://yaptide.github.io/for_developers/backend/for_developers/

### Using Docker
- Build and run with Docker Compose: `docker-compose up`
- Development mode: `docker-compose -f docker-compose-develop.yml up`
- Fast mode: `docker-compose -f docker-compose.fast.yml up`

### Key Commands
```bash
# Install dependencies
poetry install

# Install only production dependencies
poetry install --only main

# Install with test dependencies
poetry install --with test

# Format code
poetry run yapf -i -r yaptide/

# Run linting via pre-commit
poetry run pre-commit run --all-files

# Run tests
poetry run pytest

# Run Flask app (development)
poetry run flask run

# Database migrations
poetry run flask db upgrade
```

## Security Guidelines

### Secrets and Credentials
- **Never commit secrets, API keys, or passwords** to the repository
- Use environment variables for all sensitive data
- Store secrets in `.env` files (which are git-ignored)
- Use the `environs` library for loading environment variables
- Required environment variables should be documented in `.env` example files

### Environment Variables
- Flask configuration uses `FLASK_` prefix (e.g., `FLASK_SQLALCHEMY_DATABASE_URI`)
- Celery configuration: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- S3 credentials: `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENCRYPTION_PASSWORD`, `S3_ENCRYPTION_SALT`
- Backend URL: `BACKEND_INTERNAL_URL`

### Input Validation
- Always validate and sanitize user inputs
- Use SQLAlchemy ORM to prevent SQL injection
- Validate file uploads and restrict file types
- Implement proper authentication and authorization

### Dependencies
- Keep dependencies up to date for security patches
- Use Poetry to manage dependencies
- Check for vulnerabilities regularly
- Pin dependency versions in `poetry.lock`

## API and Routes

### Flask Restful
- The application uses Flask-RESTful for API endpoints
- Routes are initialized in `yaptide/routes/main_routes.py`
- Follow RESTful conventions for URL structure and HTTP methods

### Error Handling
- Return appropriate HTTP status codes
- Provide meaningful error messages
- Log errors appropriately using Flask's logger
- Use try-except blocks for error-prone operations

## Database

### ORM and Migrations
- Use SQLAlchemy ORM for database operations
- Database models are in `yaptide/persistence/models.py`
- Use Flask-Migrate (Alembic) for schema migrations
- Migration files are in `migrations/` directory (excluded from pre-commit)

### Best Practices
- Always use ORM methods instead of raw SQL
- Create migrations for all schema changes: `flask db migrate -m "description"`
- Test migrations in both directions (upgrade and downgrade)
- Never edit migration files directly after they're committed

## Celery and Background Tasks

### Task Queue
- Celery is used for asynchronous task processing
- Task definitions are in `yaptide/celery/`
- Redis is used as the broker and result backend in production
- For testing, in-memory broker is used

### Writing Tasks
- Define tasks in appropriate modules under `yaptide/celery/`
- Use appropriate task decorators from Celery
- Handle errors gracefully in tasks
- Log task execution for debugging

## CI/CD

### GitHub Actions
- Workflows are defined in `.github/workflows/`
- Main CI workflow: `test-run.yml` - runs on push and PR to master
- Deployment workflows: `deploy-master.yaml`, `manual-deploy-*.yml`
- The CI runs on both Ubuntu and Windows platforms

### CI Process
1. Checkout code
2. Setup Python 3.12
3. Install Poetry
4. Install dependencies
5. Download simulators (with timeout handling)
6. Run tests
7. Build and deploy (for master branch)

### Making Changes
- Ensure tests pass locally before pushing
- CI must pass before merging to master
- Docker images are built and pushed to GitHub Container Registry

## Common Tasks

### Adding a New Feature
1. Create a new branch from master
2. Implement feature with tests
3. Run `poetry run pytest` to verify tests pass
4. Run `poetry run pre-commit run --all-files` to check code quality
5. Create a pull request
6. Ensure CI passes
7. Get code review and merge

### Adding a New Dependency
1. Use Poetry: `poetry add package-name`
2. For dev dependencies: `poetry add --group dev package-name`
3. For test dependencies: `poetry add --group test package-name`
4. Commit both `pyproject.toml` and `poetry.lock`

### Database Schema Changes
1. Modify models in `yaptide/persistence/models.py`
2. Create migration: `poetry run flask db migrate -m "Add new field to model"`
3. Review the generated migration file
4. Apply migration: `poetry run flask db upgrade`
5. Test the migration thoroughly

## Important Notes

### Do Not Modify
- Do not edit files in the `migrations/` directory directly (they're excluded from linting)
- Do not modify `.pre-commit-config.yaml` unless specifically needed
- Do not commit `.env` files with actual secrets

### Best Practices for Copilot
- Always run tests after making changes
- Use yapf to format code before committing
- Follow existing code patterns and conventions in the repository
- Check that imports are properly organized
- Ensure proper error handling and logging
- Write tests for new functionality
- Update documentation when adding features
- Be mindful of security implications in all changes

## Resources

- [Yaptide User Docs](https://yaptide.github.io/docs/)
- [Developer Documentation](https://yaptide.github.io/for_developers/)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Celery Documentation](https://docs.celeryproject.org/)
- [Poetry Documentation](https://python-poetry.org/docs/)
- [pytest Documentation](https://docs.pytest.org/)
