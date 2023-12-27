# GHCR Packages

## Deployment

To build a flask or worker docker image and deploy it to the ghcr.io registry in pull requests, the user should write a comment `/deploy-flask` or `/deploy-worker` depending on the image needed. Packages are also automatically built and deployed when the PR is merged to master.

## Usage

All available packages are shown in the [Packages](https://github.com/orgs/yaptide/packages) section of the yaptide organisation in GitHub. Newest master branch image is available with tag `master`. For pull requests it is a PR number prefixed with `pr-`, e.g. `pr-17`. Corresponding docker pull command can be read after clicking on the package. For this case it would be:
```bash
docker pull ghcr.io/yaptide/yaptide-flask:pr-17
```

Deployed packages can be used in various ways. They can be accessed from gitpod.io or GitHub Codespaces to easily run and test them in pull requests. It is also possible to pull the images locally. It is required to log in to ghcr.io via Docker using GitHub credentials:
```bash
docker login ghcr.io --username <github_username>
```
Then it is allowed to pull the images.

## Retention policies

Both flask and worker images are automatically cleaned up in the registry based on the retention policies:

- Pull request's newest packages are removed when it is merged or closed.
- Outdated pull requests' packages are removed if they are older than 2 weeks.
- Outdated master's packages are removed if they are older than 1 month.

It is also possible to run the latter two policies manually by dispatching the `packages-retention` GitHub action. Normally it is dispatched using cron job every Monday at 04:30 AM.

To delete the packages from ghcr.io registry, it is required to use the PAT token created by organisation and repository admin with `read:packages` and `delete:packages` permissions. It should be placed in the organisation's secrets. It is not possible to use other kind of tokens, e.g. action scoped `GITHUB_TOKEN` or fine-grained token.
