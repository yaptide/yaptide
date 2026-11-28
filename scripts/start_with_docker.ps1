# check which docker version we have installed
$dockerVersion = docker -v | Select-String -Pattern "\d+\.\d+\.\d+" | ForEach-Object {$_.Matches.Groups[0].Value}

# print the docker version
Write-Host "Docker version: $dockerVersion"

# the keys of the results bucket, generated once into .env: Garage keeps them from its first start
# (https://yaptide.github.io/for_developers/backend/docker-deployment/#result-storage)
if (-not (Test-Path .env) -or -not (Select-String -Path .env -Pattern '^RESULTS_S3_ACCESS_KEY=' -Quiet)) {
  function New-Hex([int]$bytes) {
    $buffer = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    -join ($buffer | ForEach-Object { $_.ToString('x2') })
  }
  Add-Content -Path .env -Value @("RESULTS_S3_ACCESS_KEY=GK$(New-Hex 12)", "RESULTS_S3_SECRET_KEY=$(New-Hex 32)", "GARAGE_RPC_SECRET=$(New-Hex 32)")
  Write-Host "Generated the keys of the results bucket into .env, keep them"
}

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
