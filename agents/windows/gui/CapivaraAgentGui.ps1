param(
    [switch]$TrayOnly,
    [string]$InstallRoot = "$env:ProgramFiles\CapivaraAgent",
    [string]$DataRoot = "$env:ProgramData\CapivaraAgent"
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Windows.Forms,System.Drawing

$SnapshotPath = Join-Path $DataRoot 'state\gui\snapshot.json'
$LogPath = Join-Path $DataRoot 'logs\agent.log'
$Backend = Join-Path $InstallRoot 'runtime\admin_gui_backend.py'
$CommandBridge = Join-Path $InstallRoot 'gui\Invoke-CapivaraAdminCommand.ps1'
$Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
$script:LastSnapshot = $null

function Read-AgentSnapshot {
    try {
        if (Test-Path $SnapshotPath) { return (Get-Content $SnapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json) }
    } catch {}
    return $null
}
function Format-Json($Object) {
    if ($null -eq $Object) { return '' }
    return ($Object | ConvertTo-Json -Depth 12)
}
function Get-AgentLog([int]$Lines = 250) {
    if (-not (Test-Path $LogPath)) { return "Log ainda não disponível: $LogPath" }
    return ((Get-Content $LogPath -Tail $Lines -ErrorAction SilentlyContinue) -join [Environment]::NewLine)
}
function Test-IsAdministrator {
    try {
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent();$principal=New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}
function Invoke-AgentAdminCommand([string]$CommandLine) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return '' }
    if (-not $Python -or -not (Test-Path $Backend)) { return 'Backend administrativo não encontrado.' }
    $tokens = @($CommandLine.Trim() -split '\s+')
    if (Test-IsAdministrator) {
        try { return (& $Python $Backend command @tokens 2>&1 | Out-String) } catch { return $_.Exception.Message }
    }
    if (-not (Test-Path $CommandBridge)) { return 'Bridge administrativo não encontrado.' }
    $temp = Join-Path $env:TEMP ("capivara-gui-{0}.txt" -f [guid]::NewGuid().ToString('N'))
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($CommandLine))
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -PythonExe "{1}" -Backend "{2}" -OutputPath "{3}" -EncodedCommand "{4}"' -f $CommandBridge,$Python,$Backend,$temp,$encoded
    try {
        Start-Process -FilePath "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList $arguments -Verb RunAs -Wait | Out-Null
        return (Get-Content $temp -Raw -Encoding UTF8 -ErrorAction SilentlyContinue)
    } catch { return $_.Exception.Message }
    finally { Remove-Item $temp -Force -ErrorAction SilentlyContinue }
}

[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="Capivara Agent" Width="1120" Height="760" MinWidth="900" MinHeight="620" WindowStartupLocation="CenterScreen">
  <Grid Margin="16">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
    <DockPanel Grid.Row="0" Margin="0,0,0,12">
      <StackPanel Orientation="Vertical" DockPanel.Dock="Left">
        <TextBlock Text="Capivara Agent" FontSize="26" FontWeight="Bold"/>
        <TextBlock Name="Subtitle" Text="Administração local do Windows Agent" Opacity="0.7"/>
      </StackPanel>
      <Border Name="HealthBadge" DockPanel.Dock="Right" CornerRadius="12" Padding="14,7" Background="#DDD">
        <TextBlock Name="HealthText" Text="Carregando..." FontWeight="SemiBold"/>
      </Border>
    </DockPanel>
    <TabControl Grid.Row="1" Name="Tabs">
      <TabItem Header="Visão geral"><ScrollViewer><StackPanel Margin="12">
        <TextBlock Text="Identidade e saúde" FontSize="18" FontWeight="SemiBold" Margin="0,0,0,8"/>
        <TextBox Name="OverviewText" FontFamily="Consolas" IsReadOnly="True" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto" MinHeight="420"/>
      </StackPanel></ScrollViewer></TabItem>
      <TabItem Header="Atividades"><Grid Margin="12"><TextBox Name="ActivityText" FontFamily="Consolas" IsReadOnly="True" TextWrapping="NoWrap" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto"/></Grid></TabItem>
      <TabItem Header="Instâncias"><Grid Margin="12"><Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
        <ListBox Name="InstanceList" DisplayMemberPath="instance_id"/>
        <WrapPanel Grid.Row="1" Margin="0,10,0,0"><Button Name="InstanceStatus" Content="Status" Margin="3" Padding="14,6"/><Button Name="InstanceDoctor" Content="Doctor" Margin="3" Padding="14,6"/><Button Name="InstanceStart" Content="Iniciar" Margin="3" Padding="14,6"/><Button Name="InstanceStop" Content="Parar" Margin="3" Padding="14,6"/><Button Name="InstanceRestart" Content="Reiniciar" Margin="3" Padding="14,6"/></WrapPanel>
      </Grid></TabItem>
      <TabItem Header="Comandos"><Grid Margin="12"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
        <WrapPanel Name="CommandButtons"/>
        <TextBox Grid.Row="1" Name="CommandOutput" FontFamily="Consolas" IsReadOnly="True" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto" Margin="0,12,0,0"/>
      </Grid></TabItem>
      <TabItem Header="Console"><Grid Margin="12"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
        <DockPanel><Button Name="ConsoleRun" Content="Executar" DockPanel.Dock="Right" Padding="14,6" Margin="8,0,0,0"/><TextBox Name="ConsoleInput" FontFamily="Consolas" ToolTip="Somente comandos allowlisted do Agent, ex.: agent health ou instance status ID"/></DockPanel>
        <TextBox Grid.Row="1" Name="ConsoleOutput" FontFamily="Consolas" IsReadOnly="True" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto" Margin="0,12,0,0"/>
      </Grid></TabItem>
      <TabItem Header="Logs"><Grid Margin="12"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
        <StackPanel Orientation="Horizontal"><Button Name="RefreshLog" Content="Atualizar log" Padding="14,6"/><Button Name="OpenLogFolder" Content="Abrir pasta" Padding="14,6" Margin="8,0,0,0"/></StackPanel>
        <TextBox Grid.Row="1" Name="LogText" FontFamily="Consolas" IsReadOnly="True" TextWrapping="NoWrap" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto" Margin="0,12,0,0"/>
      </Grid></TabItem>
    </TabControl>
    <DockPanel Grid.Row="2" Margin="0,12,0,0"><TextBlock Name="Footer" Text="Snapshot local sanitizado" Opacity="0.65"/><Button Name="RefreshAll" Content="Atualizar" DockPanel.Dock="Right" Padding="16,6"/></DockPanel>
  </Grid>
</Window>
'@
$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)
function F([string]$Name) { $window.FindName($Name) }
$overview = F 'OverviewText'; $activity = F 'ActivityText'; $instances = F 'InstanceList'; $cmdOut = F 'CommandOutput'; $consoleIn = F 'ConsoleInput'; $consoleOut = F 'ConsoleOutput'; $logText = F 'LogText'; $healthText = F 'HealthText'; $healthBadge = F 'HealthBadge'; $subtitle = F 'Subtitle'; $footer = F 'Footer'

$commandDefinitions = @(
    @{Label='Status';Command='agent status'}, @{Label='Saúde';Command='agent health'}, @{Label='Doctor';Command='agent doctor'},
    @{Label='Capabilities';Command='agent capabilities'}, @{Label='Rede';Command='agent network'}, @{Label='Testar Controller';Command='agent controller test'},
    @{Label='Storage Pools';Command='agent storage pools'}, @{Label='Filas';Command='agent queues'}, @{Label='Reconciliar';Command='agent reconcile'}
)
foreach ($def in $commandDefinitions) {
    $button = New-Object System.Windows.Controls.Button
    $button.Content = $def.Label; $button.Margin = '3'; $button.Padding = '12,6'; $button.Tag = $def.Command
    $button.Add_Click({ $cmdOut.Text = Invoke-AgentAdminCommand ([string]$this.Tag) })
    [void](F 'CommandButtons').Children.Add($button)
}
function Refresh-View {
    $script:LastSnapshot = Read-AgentSnapshot
    if ($null -eq $script:LastSnapshot) {
        $healthText.Text='Sem snapshot'; $healthBadge.Background='#FFF3CD'; $overview.Text="Aguardando o primeiro snapshot do serviço em $SnapshotPath"; return
    }
    $health = [string]$script:LastSnapshot.overall_health
    $healthText.Text = if ($health -eq 'healthy') {'Saudável'} else {'Degradado'}
    $healthBadge.Background = if ($health -eq 'healthy') {'#D9FBE5'} else {'#FFF3CD'}
    $agent = $script:LastSnapshot.agent
    $subtitle.Text = "{0}  •  {1}  •  {2}" -f $agent.hostname,$agent.agent_id,$agent.version
    $overview.Text = Format-Json ([ordered]@{agent=$agent;task=$script:LastSnapshot.task;storage_pools=$script:LastSnapshot.storage_pools;instance_health=$script:LastSnapshot.instance_health})
    $activity.Text = Format-Json ([ordered]@{metrics=$script:LastSnapshot.metrics;reconciliation=$script:LastSnapshot.reconciliation;configuration=$script:LastSnapshot.configuration_state;content=$script:LastSnapshot.content_state;backup=$script:LastSnapshot.backup_state;broadcast=$script:LastSnapshot.broadcast_state;game_data=$script:LastSnapshot.game_data})
    $instances.ItemsSource = @($script:LastSnapshot.instances)
    $logText.Text = Get-AgentLog
    $footer.Text = "Snapshot: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
}
function Selected-InstanceId { $item=$instances.SelectedItem; if ($null -eq $item) { return $null }; return [string]$item.instance_id }
function Run-Instance([string]$Action) { $id=Selected-InstanceId; if (-not $id) { $cmdOut.Text='Selecione uma instância.'; return }; $cmdOut.Text=Invoke-AgentAdminCommand "instance $Action $id"; $window.FindName('Tabs').SelectedIndex=3; Refresh-View }
(F 'InstanceStatus').Add_Click({Run-Instance 'status'}); (F 'InstanceDoctor').Add_Click({Run-Instance 'doctor'}); (F 'InstanceStart').Add_Click({Run-Instance 'start'}); (F 'InstanceStop').Add_Click({Run-Instance 'stop'}); (F 'InstanceRestart').Add_Click({Run-Instance 'restart'})
(F 'ConsoleRun').Add_Click({ $consoleOut.Text=Invoke-AgentAdminCommand $consoleIn.Text })
$consoleIn.Add_KeyDown({ if ($_.Key -eq 'Enter') { $consoleOut.Text=Invoke-AgentAdminCommand $consoleIn.Text } })
(F 'RefreshLog').Add_Click({$logText.Text=Get-AgentLog}); (F 'OpenLogFolder').Add_Click({$folder=Split-Path $LogPath -Parent; if(Test-Path $folder){Start-Process explorer.exe $folder}}); (F 'RefreshAll').Add_Click({Refresh-View})

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Text='Capivara Agent'; $tray.Icon=[System.Drawing.SystemIcons]::Application; $tray.Visible=$true
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$openItem=$menu.Items.Add('Abrir Capivara Agent'); $healthItem=$menu.Items.Add('Atualizar saúde'); $logsItem=$menu.Items.Add('Abrir logs'); [void]$menu.Items.Add('-'); $exitItem=$menu.Items.Add('Sair da interface')
$tray.ContextMenuStrip=$menu
$show={ $window.Show(); $window.WindowState='Normal'; $window.Activate(); Refresh-View }
$openItem.Add_Click($show); $tray.Add_DoubleClick($show); $healthItem.Add_Click({Refresh-View; $tray.BalloonTipTitle='Capivara Agent'; $tray.BalloonTipText=$healthText.Text; $tray.ShowBalloonTip(1800)}); $logsItem.Add_Click({$window.Show(); $window.FindName('Tabs').SelectedIndex=5; Refresh-View}); $exitItem.Add_Click({$tray.Visible=$false; $window.Close()})
$window.Add_Closing({ if ($tray.Visible) { $_.Cancel=$true; $window.Hide() } })
Refresh-View
if ($TrayOnly) { $window.Hide() } else { $window.Show() }
[void][System.Windows.Threading.Dispatcher]::Run()
