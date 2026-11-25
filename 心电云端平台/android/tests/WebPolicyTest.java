package com.xiongbot.ecgrecords;
public final class WebPolicyTest {
    private static int checked=0;
    private static void check(boolean condition) { checked++;if(!condition)throw new AssertionError("Case "+checked); }
    public static void main(String[] args) {
        check(WebPolicy.trusted("https://62.234.150.104/"));
        check(WebPolicy.trusted("https://62.234.150.104:443/api/sessions?q=test"));
        for(String uri:new String[]{"http://62.234.150.104/","https://62.234.150.104.evil.test/","https://62.234.150.104@evil.test/","https://user@62.234.150.104/","https://62.234.150.104:444/","file:///etc/passwd","javascript:alert(1)","data:text/html,test","//62.234.150.104/"})check(!WebPolicy.trusted(uri));
        check("web/index.html".equals(WebPolicy.asset("/")));
        check("web/device-manager.html".equals(WebPolicy.asset("/devices")));
        check("web/mobile.js".equals(WebPolicy.asset("/assets/mobile.js")));
        check(WebPolicy.asset("/api/sessions")==null);
        for(String path:new String[]{"/assets/../secret","/assets/%2e%2e/secret","/assets//private","/assets/evil\\file"})check(WebPolicy.asset(path)==null);
        check(WebPolicy.sessionId("session_2026-11"));
        for(String path:new String[]{"/admin", "/admin/accounts?selected=demo", "/devices?account=demo&selected=pi-one", "/database#db-maintenance-section"})check(WebPolicy.managementPage(WebPolicy.ORIGIN+path));
        for(String uri:new String[]{WebPolicy.ORIGIN+"/", WebPolicy.ORIGIN+"/administer", WebPolicy.ORIGIN+"/api/admin/users", "https://evil.test/admin", "http://62.234.150.104/admin", null})check(!WebPolicy.managementPage(uri));
        for(String sid:new String[]{"", "../one", "a/b", "a?user=other",null})check(!WebPolicy.sessionId(sid));
        System.out.println("WebPolicy: "+checked+" cases passed");
    }
}
