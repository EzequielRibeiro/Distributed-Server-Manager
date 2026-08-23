param([string]$ControllerAddress='LocalSubnet')
$ErrorActionPreference='Stop'
if(-not ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Execute como Administrador'}
Enable-PSRemoting -Force -SkipNetworkProfileCheck
$dns=@($env:COMPUTERNAME);try{$dns+=[Net.Dns]::GetHostEntry($env:COMPUTERNAME).HostName}catch{}
$cert=New-SelfSignedCertificate -DnsName ($dns|Select-Object -Unique) -CertStoreLocation Cert:\LocalMachine\My -NotAfter (Get-Date).AddYears(2) -KeyUsage DigitalSignature,KeyEncipherment -Type SSLServerAuthentication
Get-ChildItem WSMan:\localhost\Listener|Where-Object Keys -match 'Transport=HTTPS'|Remove-Item -Recurse -Force
New-Item WSMan:\localhost\Listener -Transport HTTPS -Address * -CertificateThumbprint $cert.Thumbprint -Force|Out-Null
if(Get-NetFirewallRule -DisplayName 'Capivara WinRM HTTPS' -ErrorAction SilentlyContinue){Remove-NetFirewallRule -DisplayName 'Capivara WinRM HTTPS'}
New-NetFirewallRule -DisplayName 'Capivara WinRM HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5986 -RemoteAddress $ControllerAddress|Out-Null
Write-Host "WINRM_HTTPS_READY thumbprint=$($cert.Thumbprint)"
