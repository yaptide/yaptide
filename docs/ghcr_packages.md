# Docker images on GHCR

GitHub Container Registry is an organisation-scoped place where Docker containers can be stored and then pulled from freely in GitHub Actions and solutions like gitpod.io or GitHub Codespaces. Yaptide's packages are private and can be accessed only by the organisation members.

## Deployment

Docker images for backend (Flask) and worker can be automatically built and deployed to ghcr.io registry. Building and deployment are handled by GitHub Actions. There are two methods:

- automatic action triggered after every commit to the master,
- on-demand action triggered by `/deploy-flask` or `/deploy-worker` comment, typed by user in the Pull Request discussion.

Images from master provide a way to quickly deploy stable version of backend part of the yaptide platform. Images from pull request allows for fast way of testing new features proposed in the PR.

## Usage

All available packages are shown in the [Packages](https://github.com/orgs/yaptide/packages) section of the yaptide organisation in GitHub. Newest master branch image is available with tag `master`. For pull requests it is a PR number prefixed with `pr-`, e.g. `pr-17`. Corresponding docker pull command can be read after clicking on the package. For this case it would be:
```bash
docker pull ghcr.io/yaptide/yaptide-flask:pr-17
```

Deployed packages can be accessed from gitpod.io or GitHub Codespaces to easily run and test them in pull requests or on master branch. It might be requested to log in to ghcr.io via Docker using GitHub credentials:
```bash
docker login ghcr.io --username <github_username>
```
Then it is allowed to pull the images.

## Retention policies

GitHub Container Registry doesn't provide any retention mechanisms. It is required to use external solutions and define own GitHub Actions for this purpose. Both flask and worker images are automatically cleaned up in the registry based on the custom retention policies defined in `cleanup-closed-pr-packages` and `packages-retention` actions:

- Outdated master's packages are removed if they are older than 1 month.
- Pull request's newest packages are removed when it is merged or closed.
- Outdated pull requests' packages are removed if they are older than 2 weeks.

It is also possible to run the latter two policies manually by dispatching the `packages-retention` GitHub action. Normally it is dispatched using cron job every Monday at 04:30 AM.

To delete the packages from ghcr.io registry, it is required to use the PAT token created by organisation and repository admin with `read:packages` and `delete:packages` permissions. It should be placed in the organisation's secrets. It is not possible to use other kind of tokens, e.g. action scoped `GITHUB_TOKEN` or fine-grained token.
