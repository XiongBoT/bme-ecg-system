using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

internal static class DesktopUpdateTests
{
    private const string Release = "https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v";
    private static void Check(bool value, string label)
    {
        if (!value) { Console.Error.WriteLine(label); throw new Exception(label); }
    }
    private static string Manifest(string version, string url, string notes)
    {
        return "{\"schema\":1,\"web\":{\"build_id\":\"" + new string('a',64) +
            "\"},\"windows\":{\"version\":\"" + version + "\",\"url\":\"" + url +
            "\",\"notes\":\"" + notes + "\"},\"android\":null}";
    }
    private static UpdateResult Parse(string version, string installed)
    {
        return UpdateMetadata.Parse(Manifest(version,Release+version,"更新说明"),new Version(installed));
    }
    private sealed class Handler : HttpMessageHandler
    {
        internal Func<CancellationToken,Task<HttpResponseMessage>> Respond;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken token)
        {
            Check(request.Method==HttpMethod.Get && request.RequestUri.AbsoluteUri=="https://62.234.150.104/api/updates","fixed public update request");
            Check(request.Headers.Authorization==null && !request.Headers.Contains("Cookie"),"no update credentials or cookies");
            token.ThrowIfCancellationRequested();
            return Respond(token);
        }
    }
    // Models a response whose headers arrive promptly but whose body stalls.
    private sealed class SlowStream : Stream
    {
        public override bool CanRead {get{return true;}}
        public override bool CanSeek {get{return false;}}
        public override bool CanWrite {get{return false;}}
        public override long Length {get{throw new NotSupportedException();}}
        public override long Position {get{throw new NotSupportedException();}set{throw new NotSupportedException();}}
        public override void Flush() { }
        public override int Read(byte[] buffer,int offset,int count) {throw new NotSupportedException();}
        public override async Task<int> ReadAsync(byte[] buffer,int offset,int count,CancellationToken token)
        {await Task.Delay(30000,token);return 0;}
        public override long Seek(long offset,SeekOrigin origin) {throw new NotSupportedException();}
        public override void SetLength(long value) {throw new NotSupportedException();}
        public override void Write(byte[] buffer,int offset,int count) {throw new NotSupportedException();}
    }
    // Return valid data only after the deadline has fired, without throwing cancellation.
    private sealed class LateSuccessStream : MemoryStream
    {
        private bool waited;
        internal LateSuccessStream(string body) : base(Encoding.UTF8.GetBytes(body)) { }
        public override Task<int> ReadAsync(byte[] buffer,int offset,int count,CancellationToken token)
        {
            if(!waited) {waited=true;Check(token.WaitHandle.WaitOne(2000),"test deadline fired before late successful read");}
            return Task.FromResult(Read(buffer,offset,count));
        }
    }
    private sealed class DisposalStream : MemoryStream
    {
        internal volatile bool WasDisposed;
        protected override void Dispose(bool disposing) {WasDisposed=true;base.Dispose(disposing);}
    }
    private sealed class DeferredStreamContent : HttpContent
    {
        internal readonly TaskCompletionSource<Stream> Pending=new TaskCompletionSource<Stream>();
        protected override Task<Stream> CreateContentReadStreamAsync() {return Pending.Task;}
        protected override bool TryComputeLength(out long length) {length=0;return false;}
        protected override Task SerializeToStreamAsync(Stream stream,TransportContext context) {throw new NotSupportedException();}
    }
    private sealed class LargeStream : Stream
    {
        internal int BytesRead;
        public override bool CanRead {get{return true;}}
        public override bool CanSeek {get{return false;}}
        public override bool CanWrite {get{return false;}}
        public override long Length {get{throw new NotSupportedException();}}
        public override long Position {get{throw new NotSupportedException();}set{throw new NotSupportedException();}}
        public override void Flush() { }
        public override int Read(byte[] buffer,int offset,int count)
        {
            int read=Math.Min(count,1000000-BytesRead);
            for(int i=0;i<read;i++) buffer[offset+i]=(byte)' ';
            BytesRead+=read;return read;
        }
        public override Task<int> ReadAsync(byte[] buffer,int offset,int count,CancellationToken token)
        {token.ThrowIfCancellationRequested();return Task.FromResult(Read(buffer,offset,count));}
        public override long Seek(long offset,SeekOrigin origin) {throw new NotSupportedException();}
        public override void SetLength(long value) {throw new NotSupportedException();}
        public override void Write(byte[] buffer,int offset,int count) {throw new NotSupportedException();}
    }
    private static HttpResponseMessage Response(string body)
    {return new HttpResponseMessage(HttpStatusCode.OK){Content=new StringContent(body,Encoding.UTF8,"application/json")};}
    private static UpdateResult Fetch(Handler handler,int timeout,CancellationToken token)
    {
        using(var client=new HttpClient(handler))
            return UpdateProbe.CheckAsync(client,new Version(1,2,0,0),token,timeout).GetAwaiter().GetResult();
    }
    internal static void Run()
    {
        Check(Parse("1.10.0","1.9.0.0").Kind==UpdateKind.NewVersion,"numeric version ordering");
        Check(Parse("1.2.0","1.2.0.0").Kind==UpdateKind.Current,"omitted revision equals zero");
        Check(Parse("1.1.0","1.2.0.0").Kind==UpdateKind.Current,"older releases never downgrade");
        Check(Parse("1.2.0","1.2.0.1").Kind==UpdateKind.Current,"installed assembly revision remains supported");
        Check(Parse("65535.65535.65535","1.2.0.0").Kind==UpdateKind.NewVersion,"maximum release components accepted");
        Check(Parse("0.0.0","1.2.0.0").Kind==UpdateKind.Current,"zero release components accepted");
        foreach(string version in new[]{"1.2","1.2.0.1","65536.2.0","1.65536.0","1.2.65536","1.2.0-beta","1","01.2.0","1.02.0","1.2.00","1.2.-1","1.2.2147483648","1.2.0.0.0"," 1.2.0"})
            Check(Parse(version,"1.1.0").Kind==UpdateKind.Failed,"invalid version: "+version);
        foreach(string body in new[]{"{}","null","[]","{","{\"schema\":2,\"windows\":null}","{\"schema\":\"1\",\"windows\":null}","{\"schema\":1}","{\"schema\":1,\"windows\":{\"version\":\"1.3.0\"}}"})
            Check(UpdateMetadata.Parse(body,new Version(1,2,0)).Kind==UpdateKind.Failed,"invalid update metadata");
        Check(UpdateMetadata.Parse("{\"schema\":1,\"windows\":null}",new Version(1,2,0)).Kind==UpdateKind.Unavailable,"no release is not up-to-date");
        foreach(string url in new[]{"http://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.3.0",
            "https://github.com.evil.invalid/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.3.0",
            "https://user@github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.3.0",
            "https://github.com:444/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.3.0",
            Release+"1.3.0?next=https://evil.invalid",Release+"1.3.0#fragment",Release+"1.4.0",
            "https://github.com/other/repo/releases/tag/desktop-v1.3.0","file:///C:/malware.exe",
            "https://github.com/XiongBoT/bme-ecg-system/releases/tag/%64esktop-v1.3.0"})
            Check(UpdateMetadata.Parse(Manifest("1.3.0",url,"safe"),new Version(1,2,0)).Kind==UpdateKind.Failed,"hostile release URL rejected: "+url);
        var notes=UpdateMetadata.Parse(Manifest("1.3.0",Release+"1.3.0","text\\u0000\\u202E"+new string('x',500)),new Version(1,2,0));
        Check(notes.Metadata.Notes.Length<=400 && !notes.Metadata.Notes.Contains("\0") && !notes.Metadata.Notes.Contains("\u202E"),"release notes bounded and controls removed");

        var handler=new Handler {Respond=token=>Task.FromResult(Response(Manifest("1.3.0",Release+"1.3.0","new")))};
        Check(Fetch(handler,1000,CancellationToken.None).Kind==UpdateKind.NewVersion,"valid release returned by probe");
        handler=new Handler {Respond=token=>Task.FromResult(new HttpResponseMessage(HttpStatusCode.Redirect))};
        Check(Fetch(handler,1000,CancellationToken.None).Kind==UpdateKind.Failed,"redirect fails closed");
        string exactLimit=Manifest("1.3.0",Release+"1.3.0","safe").PadRight(16384,' ');
        handler=new Handler {Respond=token=>Task.FromResult(Response(exactLimit))};
        Check(Fetch(handler,1000,CancellationToken.None).Kind==UpdateKind.NewVersion,"body at 16 KiB boundary is accepted");
        var knownLargeStream=new LargeStream();
        handler=new Handler {Respond=token=> {
            var response=new HttpResponseMessage(HttpStatusCode.OK){Content=new StreamContent(knownLargeStream)};
            response.Content.Headers.ContentLength=1000000;
            return Task.FromResult(response);
        }};
        Check(Fetch(handler,1000,CancellationToken.None).Kind==UpdateKind.Failed && knownLargeStream.BytesRead==0,"oversized content length rejects before reading");
        var largeStream=new LargeStream();
        handler=new Handler {Respond=token=>Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){Content=new StreamContent(largeStream)})};
        Check(Fetch(handler,1000,CancellationToken.None).Kind==UpdateKind.Failed && largeStream.BytesRead<=17408,"stream reading stops at cap without content length");
        handler=new Handler {Respond=token=>Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){Content=new ByteArrayContent(new byte[]{255})})};
        Check(Fetch(handler,1000,CancellationToken.None).Kind==UpdateKind.Failed,"invalid UTF-8 is rejected");
        handler=new Handler {Respond=async token=>{await Task.Delay(30000,token);return Response("{}");}};
        var elapsed=Stopwatch.StartNew();
        Check(Fetch(handler,60,CancellationToken.None).Kind==UpdateKind.Failed && elapsed.ElapsedMilliseconds<2000,"header timeout bounded");
        handler=new Handler {Respond=token=>Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){Content=new StreamContent(new SlowStream())})};
        elapsed.Restart();
        Check(Fetch(handler,60,CancellationToken.None).Kind==UpdateKind.Failed && elapsed.ElapsedMilliseconds<2000,"body timeout bounded");
        handler=new Handler {Respond=token=>Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){
            Content=new StreamContent(new LateSuccessStream(Manifest("1.3.0",Release+"1.3.0","late release")))
        })};
        Check(Fetch(handler,20,CancellationToken.None).Kind==UpdateKind.Failed,"successful body arriving after deadline is rejected");
        var deferredContent=new DeferredStreamContent();
        handler=new Handler {Respond=token=>Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){Content=deferredContent})};
        Check(Fetch(handler,20,CancellationToken.None).Kind==UpdateKind.Failed,"deadline cancels pending body stream acquisition");
        var lateResource=new DisposalStream();
        deferredContent.Pending.SetResult(lateResource);
        Check(SpinWait.SpinUntil(()=>lateResource.WasDisposed,2000),"late stream acquired after cancellation is disposed");
        using(var cancelled=new CancellationTokenSource())
        {
            cancelled.CancelAfter(50);
            handler=new Handler {Respond=token=>Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){Content=new StreamContent(new SlowStream())})};
            bool observed=false;
            try {Fetch(handler,1000,cancelled.Token);}catch(OperationCanceledException){observed=true;}
            Check(observed,"closing cancels body read without delivering failure UI");
        }
        handler=new Handler {Respond=token=>{throw new HttpRequestException("private diagnostics");}};
        Check(Fetch(handler,1000,CancellationToken.None).Kind==UpdateKind.Failed,"network error safe failure");

        string directory=Path.Combine(Path.GetTempPath(),"ecg-update-tests-"+Guid.NewGuid().ToString("N"));
        string path=Path.Combine(directory,"last-check.txt");
        DateTime now=new DateTime(2026,11,25,0,0,0,DateTimeKind.Utc);
        try
        {
            var throttle=new UpdateThrottle(path);
            Check(throttle.TryBegin(now,false),"first automatic check");
            Check(!new UpdateThrottle(path).TryBegin(now.AddHours(23),false),"throttle persists across processes");
            Check(throttle.TryBegin(now.AddHours(24),false),"check allowed at 24 hours");
            Check(throttle.TryBegin(now.AddHours(25),true),"manual bypasses interval");
            Check(!throttle.TryBegin(now.AddHours(26),false),"manual check also throttles later automatic check");
            Check(!throttle.TryBegin(now.AddHours(20),false),"clock rollback suppresses and rebases automatic check");
            Check(throttle.TryBegin(now.AddHours(44),false),"rollback does not suppress forever");
            File.WriteAllText(path,"corrupt timestamp");
            Check(throttle.TryBegin(now.AddHours(45),false),"corrupt throttle recovered");
            using(var locked=new FileStream(path,FileMode.Open,FileAccess.ReadWrite,FileShare.None))
            {
                Check(!throttle.TryBegin(now.AddDays(7),false),"parallel automatic check denied on locked store");
                Check(throttle.TryBegin(now.AddDays(7),true),"manual check available if local store fails");
            }
        }
        finally {if(Directory.Exists(directory)) Directory.Delete(directory,true);}
        var gate=new ConnectionGate();
        Check(gate.Begin() && !gate.Begin(),"update check excludes repeated click");
        gate.Close();
        for(int i=0;i<3;i++) Check(!gate.Finish() && !gate.Begin(),"closed update check never delivers repeated late callbacks");
        Console.WriteLine("Update metadata, requests, limits, cancellation, throttling and close checks passed");
    }
}
