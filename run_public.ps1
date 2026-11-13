# 이 PC에서 앱을 띄우고 고정 주소 https://voicefit.olmuse.app/ 로 연다.
$here = $PSScriptRoot
$port = 8742
$run = Join-Path $here '.run'
New-Item -ItemType Directory -Force $run | Out-Null
$env:VOICEFIT_DAILY_CALLS = '300'
Start-Process python -WorkingDirectory $here -WindowStyle Hidden -ArgumentList '-m','streamlit','run','app.py','--server.port',$port,'--server.address','127.0.0.1','--server.headless','true','--server.enableXsrfProtection','false','--browser.gatherUsageStats','false' -RedirectStandardOutput "$run\app.log" -RedirectStandardError "$run\app.err"
Start-Process 'C:\Program Files (x86)\cloudflared\cloudflared.exe' -WindowStyle Hidden -ArgumentList 'tunnel','--config',"$env:USERPROFILE\.cloudflared\voicefit.yml",'run','voicefit' -RedirectStandardOutput "$run\tunnel.out" -RedirectStandardError "$run\tunnel.log"
