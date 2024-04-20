# check which docker version we have installed
$dockerVersion = docker -v | Select-String -Pattern "\d+\.\d+\.\d+" | ForEach-Object {$_.Matches.Groups[0].Value}

# print the docker version
Write-Host "Docker version: $dockerVersion"

# build the containers
Write-Host "Building containers:"
docker compose --file docker-compose.yml build

# try fast version, which should run on docker 25.0 and above
Write-Host "Trying to bring up containers with fast version of the command:"
$fastCmd = { docker compose --file docker-compose.yml --file docker-compose.fast.yml up --detach }
Invoke-Command -ScriptBlock $fastCmd

# if the fast version failed, try the slow version
if ($LASTEXITCODE -ne 0) {
  Write-Host "Fast version failed, trying slow version:"
  docker compose --file docker-compose.yml up --detach
}
