package top.dcpstudios.calendarwidget;
import android.app.*;
import android.content.*;
import android.webkit.CookieManager;
import android.net.Uri;
import android.os.Bundle;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Real HTTPS native UI, file and calendar acceptance with private temporary accounts. */
final class RemoteTerminalRegression {
    private final TerminalIntegrationInstrumentation test;private final Context context;
    private String stage="initialization";private String createdSchedule;private long temporaryFolder,temporaryFile;
    private RemoteTerminalRegression(TerminalIntegrationInstrumentation test){this.test=test;context=test.getTargetContext();}
    private MainActivity main(){return (MainActivity)test.activity;}
    private void login(JSONObject account)throws Exception{
        test.runOnMainSync(()->{main().netdisk();NetDiskScreen screen=main().netDiskScreen;screen.username.setText(account.optString("username"));screen.password.setText(account.optString("password"));screen.loginButton.performClick();});
        long until=System.currentTimeMillis()+60000;
        while(System.currentTimeMillis()<until&&(!NetDiskSession.isLoggedIn(context)||NetDiskSession.prefs(context).getLong("user_id",0)!=account.getLong("user_id")))Thread.sleep(200);
        TerminalClient.IO.submit(()->{}).get(90,java.util.concurrent.TimeUnit.SECONDS);
        test.check(NetDiskSession.isLoggedIn(context)&&NetDiskSession.prefs(context).getLong("user_id",0)==account.getLong("user_id"),"native Android form authenticates the expected real HTTPS account");
        test.runOnMainSync(()->test.check(TerminalIntegrationInstrumentation.findWeb(main().root)==null,"native file browser contains no WebView"));test.progress("PASS: real HTTPS native login and file browser");
    }
    private void logout()throws Exception{test.runOnMainSync(()->main().netDiskScreen.logout());TerminalClient.IO.submit(()->{}).get(60,java.util.concurrent.TimeUnit.SECONDS);test.check(!NetDiskSession.isLoggedIn(context)&&TerminalDb.get(context).schedules().isEmpty(),"native logout clears account and cached schedules");}
    private static android.widget.EditText nativeSearch(android.view.View root){if(root instanceof android.widget.EditText&&((android.widget.EditText)root).getHint()!=null&&"搜索当前列表".contentEquals(((android.widget.EditText)root).getHint()))return (android.widget.EditText)root;if(root instanceof android.view.ViewGroup)for(int i=0;i<((android.view.ViewGroup)root).getChildCount();i++){android.widget.EditText found=nativeSearch(((android.view.ViewGroup)root).getChildAt(i));if(found!=null)return found;}return null;}
    private static android.widget.ListView nativeFiles(android.view.View root){if(root instanceof android.widget.ListView)return (android.widget.ListView)root;if(root instanceof android.view.ViewGroup)for(int i=0;i<((android.view.ViewGroup)root).getChildCount();i++){android.widget.ListView found=nativeFiles(((android.view.ViewGroup)root).getChildAt(i));if(found!=null)return found;}return null;}
    private void screenshot(String filename)throws Exception{
        test.getUiAutomation().waitForIdle(500,10000);Thread.sleep(800);android.graphics.Bitmap image=test.getUiAutomation().takeScreenshot();try(OutputStream out=new FileOutputStream(new File(context.getFilesDir(),filename))){image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}
    }
    private android.view.accessibility.AccessibilityNodeInfo dialogRoot() {
        android.accessibilityservice.AccessibilityServiceInfo service=test.getUiAutomation().getServiceInfo();service.flags|=android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;test.getUiAutomation().setServiceInfo(service);
        for(android.view.accessibility.AccessibilityWindowInfo window:test.getUiAutomation().getWindows()){
            android.view.accessibility.AccessibilityNodeInfo root=window.getRoot();if(root!=null&&!root.findAccessibilityNodeInfosByText("新增日程").isEmpty())return root;
        }
        return test.getUiAutomation().getRootInActiveWindow();
    }
    private android.view.accessibility.AccessibilityNodeInfo firstEditor(android.view.accessibility.AccessibilityNodeInfo node){
        if(node==null)return null;if(node.isEditable()||"android.widget.EditText".contentEquals(node.getClassName()))return node;
        for(int i=0;i<node.getChildCount();i++){android.view.accessibility.AccessibilityNodeInfo found=firstEditor(node.getChild(i));if(found!=null)return found;}return null;
    }
    private void fileCycle(JSONObject data)throws Exception{
        NetDiskSession.Account account=NetDiskSession.account(context);long project=data.getLong("project_id");JSONObject root=NetDiskFiles.root(context,project,account);
        JSONObject folder=NetDiskFiles.createFolder(context,root.getLong("id"),project,"APK 原生文件验收",account);temporaryFolder=folder.getLong("id");
        File input=new File(context.getCacheDir(),"APK-验收原格式.bin");byte[] expected=new byte[1024*1024+713];for(int i=0;i<expected.length;i++)expected[i]=(byte)(i*31+17);
        try(OutputStream out=new FileOutputStream(input)){out.write(expected);}
        JSONObject uploaded=NetDiskFiles.upload(context,Uri.fromFile(input),temporaryFolder,project,account,text->{});temporaryFile=uploaded.getLong("id");input.delete();
        test.check("APK-验收原格式.bin".equals(uploaded.optString("name")),"native upload preserves the original filename and extension");
        ByteArrayOutputStream downloaded=new ByteArrayOutputStream();NetDiskFiles.download(context,temporaryFile,downloaded,account,text->{});test.check(Arrays.equals(expected,downloaded.toByteArray()),"native two-chunk upload and streamed download preserve original binary bytes");
        NetDiskFiles.json(context,"/api/files/"+temporaryFile,"PATCH",new JSONObject().put("name","重命名-原格式.bin").put("parent_id",root.getLong("id")),account);
        List<JSONObject> files=NetDiskFiles.list(context,root.getLong("id"),account);boolean found=false;for(JSONObject row:files)if(row.getLong("id")==temporaryFile)found="重命名-原格式.bin".equals(row.optString("name"));test.check(found,"native rename and move update the server file tree");
        JSONObject projectRow=NetDiskFiles.json(context,"/api/projects/"+project,"GET",null,account).getJSONObject("project");test.runOnMainSync(()->main().netDiskScreen.openProject(projectRow));TerminalClient.IO.submit(()->{}).get(60,java.util.concurrent.TimeUnit.SECONDS);Thread.sleep(1000);
        test.runOnMainSync(()->{android.widget.EditText search=nativeSearch(main().root);if(search==null)throw new AssertionError("Native file search is available");search.setText("重命名-原格式.bin");});test.waitForIdleSync();test.getUiAutomation().waitForIdle(250,5000);
        test.runOnMainSync(()->{android.widget.ListView filesView=nativeFiles(main().root);test.check(filesView!=null&&TerminalIntegrationInstrumentation.textPresent(filesView,"重命名-原格式.bin")&&TerminalIntegrationInstrumentation.findWeb(main().root)==null,"native ListView renders real project files");});screenshot("native-project-files.png");
        NetDiskFiles.json(context,"/api/files/"+temporaryFile,"DELETE",null,account);temporaryFile=0;NetDiskFiles.json(context,"/api/files/"+temporaryFolder,"DELETE",null,account);temporaryFolder=0;
        JSONObject personal=NetDiskFiles.root(context,0,account);JSONObject personalFolder=NetDiskFiles.createFolder(context,personal.getLong("id"),0,"APK 个人目录验收",account);temporaryFolder=personalFolder.getLong("id");
        test.check(NetDiskFiles.list(context,personal.getLong("id"),account).stream().anyMatch(r->r.optLong("id")==temporaryFolder),"native personal directory uses the current account scope");NetDiskFiles.json(context,"/api/files/"+temporaryFolder,"DELETE",null,account);temporaryFolder=0;
        test.progress("PASS: native original-byte upload, download, rename, move, delete and personal directory");
    }
    private void scheduleCycle()throws Exception{
        NetDiskSession.Account account=NetDiskSession.account(context);final String title="APK 本人新增日程验收 "+UUID.randomUUID().toString().substring(0,8);
        test.runOnMainSync(()->{main().agenda();ScheduleEditor.show(main(),null);});test.getUiAutomation().waitForIdle(500,10000);
        android.view.accessibility.AccessibilityNodeInfo window=dialogRoot(),name=firstEditor(window);boolean filled=false;
        if(name!=null){Bundle text=new Bundle();text.putCharSequence(android.view.accessibility.AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,title);filled=name.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_SET_TEXT,text);}
        test.check(filled,"native schedule title can be entered in the Android form");screenshot("native-new-schedule.png");
        window=dialogRoot();boolean submitted=false;for(android.view.accessibility.AccessibilityNodeInfo save:window.findAccessibilityNodeInfosByText("保存到服务器"))if(save.isClickable()){submitted=save.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK);break;}test.check(submitted,"native schedule save button invokes the account-bound request");
        long until=System.currentTimeMillis()+45000;while(System.currentTimeMillis()<until&&createdSchedule==null){for(JSONObject row:TerminalDb.get(context).schedules())if(title.equals(row.optString("title")))createdSchedule=row.optString("id");if(createdSchedule==null)Thread.sleep(200);}
        test.check(createdSchedule!=null,"native form creates the current account's server schedule");TerminalClient.sync(context,false);
        test.check(TerminalDb.get(context).schedules().stream().anyMatch(row->createdSchedule.equals(row.optString("id"))),"native create adds the current account's server schedule");
        CalendarStore.prefs(context).edit().putBoolean("force:"+createdSchedule,true).commit();TerminalClient.sync(context,false);test.check(!TaskOverrides.pending(context,createdSchedule),"installed-version force marker is acknowledged and removed");
        TerminalDb.get(context).clearAccountData();TerminalClient.sync(context,false);JSONObject remote=NetDiskSession.requestMethod(context,"/api/mobile/terminal/schedules","GET",null,account).data;boolean completed=false;
        for(int i=0;i<remote.getJSONArray("schedules").length();i++){JSONObject row=remote.getJSONArray("schedules").getJSONObject(i);if(createdSchedule.equals(row.optString("id")))completed=row.optBoolean("forced_completed")&&row.optBoolean("completed");}
        test.check(completed,"server force completion survives native cache deletion and re-download");
        CalendarStore.prefs(context).edit().putBoolean("force:"+createdSchedule,false).commit();TerminalClient.sync(context,false);CalendarData.Event target=null;for(CalendarData.Event e:CalendarStore.read(context))if(createdSchedule.equals(e.uid))target=e;
        test.check(target!=null&&!target.completed&&!target.forcedCompleted,"cancelling force completion is acknowledged by the server");
        test.runOnMainSync(()->{main().events=CalendarStore.read(main());main().agenda();});screenshot("native-ordinary-schedules.png");
        NetDiskSession.requestMethod(context,"/api/mobile/terminal/schedules/"+java.net.URLEncoder.encode(createdSchedule,"UTF-8"),"DELETE",null,account);createdSchedule=null;test.progress("PASS: native personal create, force sync, re-download and force cancellation");
    }
    private void execute()throws Exception{
        ByteArrayOutputStream input=new ByteArrayOutputStream();try(InputStream file=new FileInputStream(new File(context.getFilesDir(),"netdisk-merge-qa.json"))){byte[] bytes=new byte[4096];int n;while((n=file.read(bytes))!=-1)input.write(bytes,0,n);}
        JSONObject data=new JSONObject(new String(input.toByteArray(),StandardCharsets.UTF_8)),accounts=data.getJSONObject("accounts");NetDiskSession.clear(context);
        test.runOnMainSync(()->CookieManager.getInstance().removeAllCookies(null));CookieManager.getInstance().flush();Thread.sleep(200);
        NetDiskSession.prefs(context).edit().putString("origin",NetDiskSession.validateOrigin(data.getString("url"))).putBoolean("signed_out",true).commit();CalendarStore.prefs(context).edit().putInt("interval",0).commit();TerminalClient.prefs(context).edit().putBoolean("notifications",false).putBoolean("notification_setup_seen",true).commit();
        test.activity=test.startActivitySync(new Intent(context,MainActivity.class).putExtra("page","netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));screenshot("native-login.png");
        stage="administrator native login";login(accounts.getJSONObject("super"));test.check(NetDiskSession.canTerminal(context),"real administrator retains Terminal capability");
        stage="device session restore";NetDiskSession.ensure(context,true);test.runOnMainSync(()->{main().finish();});test.activity=test.startActivitySync(new Intent(context,MainActivity.class).putExtra("page","netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));TerminalClient.IO.submit(()->{}).get(60,java.util.concurrent.TimeUnit.SECONDS);test.check(NetDiskSession.isLoggedIn(context),"reopening APK restores persisted HttpOnly device session without password");
        stage="administrator logout";logout();stage="ordinary native login";login(accounts.getJSONObject("ordinary"));test.check(!NetDiskSession.canTerminal(context)&&TerminalDb.get(context).messages("").isEmpty(),"ordinary account cannot reuse administrator messages");
        for(JSONObject row:TerminalDb.get(context).schedules())test.check("netdisk".equals(row.optString("source")),"ordinary schedule belongs to the account");
        stage="native file cycle";fileCycle(data);stage="native server calendar cycle";scheduleCycle();stage="ordinary logout";logout();
    }
    private void cleanup(){
        try{NetDiskSession.Account account=NetDiskSession.account(context);if(createdSchedule!=null)NetDiskSession.requestMethod(context,"/api/mobile/terminal/schedules/"+java.net.URLEncoder.encode(createdSchedule,"UTF-8"),"DELETE",null,account);if(temporaryFile>0)NetDiskFiles.json(context,"/api/files/"+temporaryFile,"DELETE",null,account);if(temporaryFolder>0)NetDiskFiles.json(context,"/api/files/"+temporaryFolder,"DELETE",null,account);}catch(Exception ignored){}
        try{NetDiskSession.logout(context);}catch(Exception ignored){}NetDiskSession.observeWebLogin(context,true);new File(context.getFilesDir(),"netdisk-merge-qa.json").delete();if(test.activity!=null)test.runOnMainSync(()->test.activity.finish());
    }
    static void run(TerminalIntegrationInstrumentation test){RemoteTerminalRegression remote=new RemoteTerminalRegression(test);Bundle result=new Bundle();int outcome=Activity.RESULT_OK;
        try{remote.execute();result.putString("stream","PASS: real HTTPS native login, files, personal schedules and server force completion\n");}
        catch(Throwable error){outcome=Activity.RESULT_CANCELED;result.putString("stream","FAIL: native remote acceptance at "+remote.stage+" ("+error.getClass().getSimpleName()+(error instanceof AssertionError?": "+error.getMessage():"")+")\n");try{remote.screenshot("native-failure.png");}catch(Exception ignored){}}
        finally{remote.cleanup();test.finish(outcome,result);}
    }
}
