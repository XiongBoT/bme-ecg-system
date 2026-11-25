using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: AssemblyTitle("心电工作台")]
[assembly: AssemblyDescription("心电云端平台 HTTPS 桌面入口")]
[assembly: AssemblyProduct("心电工作台")]
[assembly: AssemblyVersion("1.2.0.0")]

internal static class Launcher
{
    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        Application.Run(new ConnectionWindow(Array.IndexOf(args, "--connection") < 0));
        return 0;
    }

    internal static bool OpenWorkspace(Rectangle area)
    {
        string[] roots = {
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData)
        };
        string[] browsers = { @"Microsoft\Edge\Application\msedge.exe", @"Google\Chrome\Application\chrome.exe" };
        foreach (string browser in browsers)
        {
            foreach (string root in roots)
            {
                if (String.IsNullOrEmpty(root)) continue;
                string path = Path.Combine(root, browser);
                if (!File.Exists(path)) continue;
                if (TryStart(path, LaunchPolicy.BrowserArguments(area), false)) return true;
            }
        }
        // Default browser remains available when Edge/Chrome is not installed.
        return OpenBrowser();
    }

    internal static bool OpenBrowser() { return TryStart(LaunchPolicy.CloudUrl, "", true); }
    internal static bool OpenRelease(UpdateMetadata release)
    {
        return release!=null && UpdateMetadata.IsOfficialUrl(release.Url.AbsoluteUri,release.VersionText) &&
            TryStart(release.Url.AbsoluteUri,"",true);
    }

    private static bool TryStart(string file, string arguments, bool shell)
    {
        try
        {
            using (Process process = Process.Start(new ProcessStartInfo {
                FileName = file,
                Arguments = arguments,
                UseShellExecute = shell,
                WorkingDirectory = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)
            })) { }
            return true;
        }
        catch (System.ComponentModel.Win32Exception) { return false; }
        catch (InvalidOperationException) { return false; }
        catch (System.Security.SecurityException) { return false; }
    }
}

internal sealed class ConnectionWindow : Form
{
    private readonly ConnectionGate gate = new ConnectionGate();
    private readonly ConnectionGate updateGate = new ConnectionGate();
    private readonly UpdateThrottle updateThrottle = UpdateThrottle.ForCurrentUser();
    private readonly CancellationTokenSource lifetime = new CancellationTokenSource();
    private readonly bool autoOpen;
    private readonly Label status = new Label();
    private readonly Label detail = new Label();
    private readonly Button open = new Button();
    private readonly Button retry = new Button();
    private readonly LinkLabel updates = new LinkLabel();
    private readonly Label updateStatus = new Label();
    private bool workspaceOpened, updatePromptShowing;

    internal ConnectionWindow(bool autoOpen)
    {
        this.autoOpen = autoOpen;
        Text = "心电工作台 · 连接助手";
        Font = new Font("Microsoft YaHei UI", 10F);
        AutoScaleMode = AutoScaleMode.Font;
        ClientSize = new Size(570, 430);
        AutoScroll = true;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(246, 249, 247);
        MaximizeBox = false;
        Icon = Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location);

        var layout = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize=true, MinimumSize=new Size(500,0), Padding = new Padding(28), ColumnCount = 1, RowCount = 7 };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(layout);
        layout.Controls.Add(new Label {Text="心电工作台",AutoSize=true,Font=new Font(Font.FontFamily,23F,FontStyle.Bold),ForeColor=Color.FromArgb(8,127,113),Margin=new Padding(0,0,0,8)});
        layout.Controls.Add(new Label {Text="记录与分析保存在云端，换一台电脑也能继续查看。",AutoSize=true,ForeColor=Color.FromArgb(95,117,109),Margin=new Padding(0,0,0,22)});
        var panel = new TableLayoutPanel {Dock=DockStyle.Fill,AutoSize=true,MinimumSize=new Size(0,115),ColumnCount=1,RowCount=2,BackColor=Color.White,Padding=new Padding(18),Margin=new Padding(0,0,0,18)};
        panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));panel.RowStyles.Add(new RowStyle(SizeType.Percent,100));
        status.Text="正在连接云端…";status.AutoSize=true;status.Font=new Font(Font,FontStyle.Bold);status.Margin=new Padding(0,0,0,9);
        detail.Text="连接成功后自动打开工作台。";detail.Dock=DockStyle.Fill;detail.AutoSize=true;detail.ForeColor=Color.FromArgb(95,117,109);detail.MaximumSize=new Size(455,0);
        panel.Controls.Add(status);panel.Controls.Add(detail);layout.Controls.Add(panel);
        var actions = new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Fill,Margin=new Padding(0),WrapContents=true};
        Configure(open,"打开工作台",true);open.Enabled=false;open.Click+=delegate {OpenWorkspace();};
        Configure(retry,"重新连接",false);retry.Click+=delegate {CheckConnection();};
        var browser=new Button();Configure(browser,"浏览器打开",false);browser.Click+=delegate {if(!Launcher.OpenBrowser()) ShowLaunchError();};
        actions.Controls.Add(open);actions.Controls.Add(retry);actions.Controls.Add(browser);layout.Controls.Add(actions);
        var links=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Fill,Margin=new Padding(0,12,0,8)};
        var shortcut=new LinkLabel {Text="创建桌面快捷方式",AutoSize=true,Margin=new Padding(0,5,20,5),LinkColor=Color.FromArgb(8,127,113)};
        shortcut.LinkClicked+=delegate {CreateShortcut();};
        var address=new LinkLabel {Text="复制云端地址",AutoSize=true,Margin=new Padding(0,5,0,5),LinkColor=Color.FromArgb(8,127,113)};
        address.LinkClicked+=delegate {try {Clipboard.SetText(LaunchPolicy.CloudUrl);detail.Text="云端地址已复制，可粘贴到浏览器打开。";} catch(ExternalException) {detail.Text="剪贴板暂不可用。云端地址："+LaunchPolicy.CloudUrl;}};
        updates.Text="检查更新";updates.AutoSize=true;updates.Margin=new Padding(20,5,0,5);updates.LinkColor=Color.FromArgb(8,127,113);
        updates.LinkClicked+=delegate {CheckUpdates(true);};
        links.Controls.Add(shortcut);links.Controls.Add(address);links.Controls.Add(updates);layout.Controls.Add(links);
        updateStatus.AutoSize=true;updateStatus.MaximumSize=new Size(480,0);updateStatus.ForeColor=Color.FromArgb(95,117,109);
        updateStatus.Text="更新只作提醒，可继续使用当前版本。";layout.Controls.Add(updateStatus);
        layout.Controls.Add(new Label {Text="Windows 版 "+Assembly.GetExecutingAssembly().GetName().Version.ToString(3)+" · 需要联网 · 沿用已有心电平台账号",AutoSize=true,ForeColor=Color.FromArgb(117,135,127),Font=new Font(Font.FontFamily,9F),Margin=new Padding(0,8,0,0)});
        // Start both requests before awaiting either; opening the workspace never waits for updates.
        Shown+=delegate {CheckUpdates(false);CheckConnection();};
        FormClosing+=delegate {gate.Close();updateGate.Close();lifetime.Cancel();};
        FormClosed+=delegate {lifetime.Dispose();};
    }

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        Rectangle area=Screen.FromControl(this).WorkingArea;
        MaximumSize=area.Size;
        Bounds=LaunchPolicy.ConnectionBounds(area,Size);
    }

    private void Configure(Button button,string caption,bool primary)
    {
        button.Text=caption;button.AutoSize=true;button.MinimumSize=new Size(132,42);button.Margin=new Padding(0,0,10,0);
        button.FlatStyle=FlatStyle.Flat;button.FlatAppearance.BorderColor=Color.FromArgb(211,227,218);
        button.BackColor=primary?Color.FromArgb(8,127,113):Color.White;button.ForeColor=primary?Color.White:Color.FromArgb(44,74,62);
    }

    private async void CheckConnection()
    {
        if(!gate.Begin()) return;
        retry.Enabled=false;open.Enabled=false;status.Text="正在连接云端…";
        detail.Text=autoOpen?"连接成功后自动打开工作台。也可以直接用浏览器打开。":"正在检查公开入口，不读取账号或采集记录。";
        ConnectionResult result;
        try
        {
            using(var handler=new HttpClientHandler {AllowAutoRedirect=false,UseCookies=false})
            using(var client=new HttpClient(handler) {Timeout=TimeSpan.FromSeconds(6)})
                result=await ConnectionProbe.CheckAsync(client,lifetime.Token);
        }
        catch(OperationCanceledException) {return;}
        if(!gate.Finish() || IsDisposed) return;
        retry.Enabled=true;open.Enabled=true;
        status.Text=result.Kind==ConnectionKind.Ready?"已连接云端":"暂时无法连接";
        detail.Text=result.Message;
        if(result.Kind==ConnectionKind.Ready && autoOpen) OpenWorkspace();
    }

    private void OpenWorkspace()
    {
        if(!Launcher.OpenWorkspace(Screen.FromControl(this).WorkingArea)) {ShowLaunchError();return;}
        workspaceOpened=true;
        if(!autoOpen) Close();else FinishStartup();
    }
    private void FinishStartup()
    {
        if(workspaceOpened && autoOpen && !updateGate.IsRunning && !updatePromptShowing && !IsDisposed && !Disposing) Close();
    }
    private async void CheckUpdates(bool manual)
    {
        if(!updateGate.Begin()) return;
        if(!updateThrottle.TryBegin(DateTime.UtcNow,manual)) {updateGate.Finish();return;}
        updates.Enabled=false;
        if(manual) updateStatus.Text="正在检查更新…";
        CancellationToken token=lifetime.Token;
        // Yield once so even an immediately completed update cannot delay the connection probe.
        await Task.Yield();
        if(token.IsCancellationRequested) return;
        UpdateResult result;
        try
        {
            using(var client=UpdateProbe.CreateClient())
                result=await UpdateProbe.CheckAsync(client,Assembly.GetExecutingAssembly().GetName().Version,token);
        }
        catch(OperationCanceledException) {return;}
        if(!updateGate.Finish() || IsDisposed || Disposing) return;
        updates.Enabled=true;
        if(result.Kind==UpdateKind.NewVersion)
        {
            updateStatus.Text="有新版 "+result.Metadata.VersionText+" 可用，可继续使用当前版本。";
            updatePromptShowing=true;
            try
            {
                using(var prompt=new UpdateNotice(result.Metadata))
                    if(prompt.ShowDialog(this)==DialogResult.OK && !Launcher.OpenRelease(result.Metadata))
                        updateStatus.Text="未能打开版本页面，请稍后重新检查更新。";
            }
            finally {updatePromptShowing=false;}
        }
        else if(manual)
        {
            if(result.Kind==UpdateKind.Current) updateStatus.Text="当前无需更新。";
            else if(result.Kind==UpdateKind.Unavailable) updateStatus.Text="暂未提供 Windows 更新信息，可继续使用当前版本。";
            else updateStatus.Text="暂时无法检查更新，请检查网络后重试。当前版本仍可继续使用。";
        }
        FinishStartup();
    }
    private void ShowLaunchError()
    {
        status.Text="浏览器未能启动";
        detail.Text="请尝试“浏览器打开”，或复制云端地址到 Edge / Chrome："+LaunchPolicy.CloudUrl;
    }
    private void CreateShortcut()
    {
        string path=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"心电工作台.lnk");
        if(File.Exists(path)) {detail.Text="桌面上已有同名快捷方式，未覆盖。需要更换时请先移走旧快捷方式。";return;}
        object shell=null,shortcut=null;
        try
        {
            Type shellType=Type.GetTypeFromProgID("WScript.Shell");
            if(shellType==null) throw new InvalidOperationException();
            shell=Activator.CreateInstance(shellType);
            shortcut=shellType.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{path});
            Type type=shortcut.GetType();string executable=Assembly.GetExecutingAssembly().Location;
            type.InvokeMember("TargetPath",BindingFlags.SetProperty,null,shortcut,new object[]{executable});
            type.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,shortcut,new object[]{Path.GetDirectoryName(executable)});
            type.InvokeMember("Description",BindingFlags.SetProperty,null,shortcut,new object[]{"心电云端工作台"});
            type.InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,null);
            detail.Text="桌面快捷方式已创建。请保留当前解压文件夹，移动后需重新创建。";
        }
        catch(Exception error)
        {
            if(!(error is COMException || error is TargetInvocationException || error is UnauthorizedAccessException || error is IOException || error is InvalidOperationException)) throw;
            detail.Text="未能创建快捷方式。可以在资源管理器中右键“心电工作台.exe”手动创建。";
        }
        finally {if(shortcut!=null && Marshal.IsComObject(shortcut)) Marshal.ReleaseComObject(shortcut);if(shell!=null && Marshal.IsComObject(shell)) Marshal.ReleaseComObject(shell);}
    }
}

internal sealed class UpdateNotice : Form
{
    internal UpdateNotice(UpdateMetadata release)
    {
        Text="心电工作台 · 发现新版";Font=new Font("Microsoft YaHei UI",10F);
        AutoScaleMode=AutoScaleMode.Font;StartPosition=FormStartPosition.CenterParent;
        ClientSize=new Size(480,280);MinimumSize=new Size(360,240);MaximizeBox=false;MinimizeBox=false;
        BackColor=Color.FromArgb(246,249,247);
        var layout=new TableLayoutPanel {Dock=DockStyle.Fill,Padding=new Padding(22),ColumnCount=1,RowCount=3};
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));layout.RowStyles.Add(new RowStyle(SizeType.Percent,100));layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(new Label {Text="新版本 "+release.VersionText+" 可用",AutoSize=true,Font=new Font(Font,FontStyle.Bold),UseMnemonic=false,Margin=new Padding(0,0,0,12)});
        var notes=new TextBox {Text=(release.Notes.Length>0?release.Notes+Environment.NewLine+Environment.NewLine:"")+"可前往官方版本页面查看说明并自行下载，也可稍后继续使用当前版本。",Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,BorderStyle=BorderStyle.None,BackColor=BackColor,TabStop=false};
        layout.Controls.Add(notes);
        var actions=new FlowLayoutPanel {AutoSize=true,Dock=DockStyle.Fill,FlowDirection=FlowDirection.RightToLeft,Margin=new Padding(0,16,0,0)};
        var later=new Button {Text="稍后",DialogResult=DialogResult.Cancel,AutoSize=true,MinimumSize=new Size(100,36)};
        var view=new Button {Text="查看新版",DialogResult=DialogResult.OK,AutoSize=true,MinimumSize=new Size(100,36)};
        actions.Controls.Add(later);actions.Controls.Add(view);layout.Controls.Add(actions);Controls.Add(layout);
        CancelButton=later;AcceptButton=later;
    }
    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        Rectangle area=Screen.FromControl(this).WorkingArea;MaximumSize=area.Size;
        Bounds=LaunchPolicy.ConnectionBounds(area,Size);
    }
}
