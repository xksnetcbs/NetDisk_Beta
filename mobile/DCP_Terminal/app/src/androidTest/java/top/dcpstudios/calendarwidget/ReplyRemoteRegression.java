package top.dcpstudios.calendarwidget;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.view.View;
import android.widget.EditText;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/** Actual HTTPS and composer clicks, restricted to the parent's temporary QA accounts. */
final class ReplyRemoteRegression {
    final TerminalIntegrationInstrumentation test;
    final Context c;
    String stage="initialization";
    long thread;
    JSONArray messageIds=new JSONArray();
    ReplyRemoteRegression(TerminalIntegrationInstrumentation test){this.test=test;c=test.getTargetContext();}
    MainActivity main(){return (MainActivity)test.activity;}
    void screenshot(String name)throws Exception{
        test.getUiAutomation().waitForIdle(400,10000);Thread.sleep(300);android.graphics.Bitmap image=test.getUiAutomation().takeScreenshot();
        if(image==null)throw new AssertionError("Reply screenshot unavailable");
        try(OutputStream out=new FileOutputStream(new File(c.getFilesDir(),name))){image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}finally{image.recycle();}
    }
    JSONObject fixture()throws Exception{
        try(InputStream in=new FileInputStream(new File(c.getFilesDir(),"netdisk-merge-qa.json"));ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] bytes=new byte[4096];int n;while((n=in.read(bytes))!=-1)out.write(bytes,0,n);return new JSONObject(out.toString("UTF-8"));
        }
    }
    JSONObject nativeJson(String path,String method,JSONObject body)throws Exception{return NetDiskSession.requestMethod(c,path,method,body,NetDiskSession.account(c)).data;}
    void execute()throws Exception{
        JSONObject data=fixture(),accounts=data.getJSONObject("accounts"),user=accounts.getJSONObject("super");
        test.check(user.getLong("user_id")!=1&&accounts.getJSONObject("ordinary").getLong("user_id")!=1,"reply acceptance uses dedicated QA users only");
        NetDiskSession.observeWebLogin(c,true);test.runOnMainSync(()->CookieManager.getInstance().removeAllCookies(null));CookieManager.getInstance().flush();Thread.sleep(150);
        NetDiskSession.prefs(c).edit().putString("origin",NetDiskSession.validateOrigin(data.getString("url"))).putBoolean("signed_out",true).commit();
        CalendarStore.prefs(c).edit().putInt("interval",0).commit();TerminalClient.prefs(c).edit().putBoolean("notifications",false).putBoolean("notification_setup_seen",true).commit();
        test.activity=test.startActivitySync(new Intent(c,MainActivity.class).putExtra("page","netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        stage="native QA login";
        test.runOnMainSync(()->{NetDiskScreen form=main().netDiskScreen;form.username.setText(user.optString("username"));form.password.setText(user.optString("password"));form.loginButton.performClick();});
        long until=System.currentTimeMillis()+60000;while(System.currentTimeMillis()<until&&(!NetDiskSession.isLoggedIn(c)||NetDiskSession.prefs(c).getLong("user_id",0)!=user.getLong("user_id")))Thread.sleep(150);
        TerminalClient.IO.submit(()->{}).get(90,TimeUnit.SECONDS);test.check(NetDiskSession.isLoggedIn(c)&&NetDiskSession.prefs(c).getLong("user_id",0)==user.getLong("user_id"),"real reply QA authenticates through native login fields");
        stage="private QA seed";String marker="DCP_NATIVE_UI_REPLY_"+UUID.randomUUID().toString().substring(0,8);
        JSONObject created=nativeJson("/api/inbox/threads","POST",new JSONObject().put("recipients",new JSONArray().put(accounts.getJSONObject("ordinary").getLong("user_id"))).put("subject","专用消息回复验收").put("content_md",marker));
        thread=created.getJSONObject("thread").getLong("id");JSONArray originals=nativeJson("/api/inbox/threads/"+thread+"/messages","GET",null).getJSONArray("items");messageIds.put(originals.getJSONObject(0).getLong("id"));
        stage="real terminal snapshot";JSONObject captured=null;until=System.currentTimeMillis()+30000;
        while(captured==null&&System.currentTimeMillis()<until){JSONArray rows=TerminalClient.requestBound(c,"/snapshot",null,NetDiskSession.account(c)).data.optJSONArray("messages");
            if(rows!=null)for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if("netdisk".equals(row.optString("source"))&&marker.equals(row.optString("body")))captured=row;}if(captured==null)Thread.sleep(500);
        }
        test.check(captured!=null,"real QA message reaches the same Terminal snapshot used by the APK");
        TerminalDb.get(c).put(captured);JSONObject anchor=TerminalDb.get(c).message(captured.getLong("id"));
        test.check(anchor!=null&&anchor.getString("source_key").equals(anchor.getJSONObject("payload").getString("message_uid")),"real Terminal snapshot retains canonical message identity through the local cache");
        String chat=anchor.getJSONObject("payload").getString("chat_id"),expiredUid="netdisk:"+anchor.getJSONObject("payload").getString("instance_id")+":inbox:9223372036854775807";
        JSONObject capability=TerminalClient.requestBound(c,"/replies/capabilities?source=netdisk&chat_id="+android.net.Uri.encode(chat)+"&message_uid="+android.net.Uri.encode(expiredUid),null,NetDiskSession.account(c)).data;
        test.check(!capability.optBoolean("reply_enabled"),"a forged or expired message source cannot authorize sending even inside a valid conversation");
        JSONObject cached=new JSONObject(anchor.toString());cached.put("source_key",expiredUid);cached.getJSONObject("payload").put("message_uid",expiredUid);TerminalDb.get(c).put(cached);
        test.runOnMainSync(()->new MessageScreen(main()).detail(TerminalDb.get(c).message(cached.optLong("id"))));
        EditText draft=(EditText)main().root.findViewWithTag("message-reply-draft");View send=main().root.findViewWithTag("message-reply-send");
        test.check(draft!=null&&send!=null,"normal MessageScreen detail navigation exposes the actual reply composer");MessageReplyRegression.await(test,draft::isEnabled);
        test.check(draft.isEnabled(),"actual current history replaces an expired cached source and rechecks server permission before enabling the editor");
        stage="native quick chip and input";View chip=NativeDiskUiRegression.described(main().root,"收到");MessageReplyRegression.tap(test,chip);
        test.runOnMainSync(()->{test.check("收到".contentEquals(draft.getText()),"actual touch on the quick reply chip fills the editor");draft.setText("");});
        MessageReplyRegression.tap(test,draft);MessageReplyRegression.editorFocus(test,draft);test.runOnMainSync(()->test.check(draft.hasFocus(),"actual touch focuses the authorized reply editor"));test.sendStringSync(marker+"_native_reply");
        test.runOnMainSync(()->test.check((marker+"_native_reply").contentEquals(draft.getText()),"real keyboard events enter the reply in the native composer"));
        test.check(TerminalIntegrationInstrumentation.findWeb(main().root)==null,"actual conversation and composer contain native views only");screenshot("native-reply-input.png");
        stage="actual native send";MessageReplyRegression.tap(test,send);MessageReplyRegression.await(test,()->MessageReply.prefs(c).getAll().isEmpty());
        test.runOnMainSync(()->test.check(TerminalIntegrationInstrumentation.textPresent(main().root,"发送成功"),"native send shows success only after server confirmed ACK"));
        JSONArray messages=nativeJson("/api/inbox/threads/"+thread+"/messages","GET",null).getJSONArray("items");test.check(messages.length()==2,"native composer produces exactly one real private QA reply");
        JSONObject sent=messages.getJSONObject(1);messageIds.put(sent.getLong("id"));test.check(sent.getLong("sender_id")==user.getLong("user_id")&&(marker+"_native_reply").equals(sent.getString("content_md")),"native reply persists authenticated sender and original text");
        Thread.sleep(4500);TerminalClient.IO.submit(()->{}).get(30,TimeUnit.SECONDS);test.waitForIdleSync();screenshot("native-reply-confirmed.png");
        test.progress("PASS: real HTTPS native quick chip, text input, confirmed reply and actual authenticated message");
    }
    void cleanup(){
        try{NetDiskSession.logout(c);}catch(Exception ignored){}NetDiskSession.observeWebLogin(c,true);
        try{new File(c.getFilesDir(),"netdisk-merge-qa.json").delete();JSONObject ids=new JSONObject().put("thread_ids",new JSONArray().put(thread)).put("message_ids",messageIds);
            try(OutputStream out=new FileOutputStream(new File(c.getFilesDir(),"native-reply-cleanup.json"))){out.write(ids.toString().getBytes(StandardCharsets.UTF_8));}
        }catch(Exception ignored){}if(test.activity!=null)test.runOnMainSync(()->test.activity.finish());
    }
    static void run(TerminalIntegrationInstrumentation test){ReplyRemoteRegression suite=new ReplyRemoteRegression(test);Bundle result=new Bundle();int code=Activity.RESULT_OK;
        try{suite.execute();result.putString("stream","PASS: real HTTPS native quick reply\n");}
        catch(Throwable error){code=Activity.RESULT_CANCELED;result.putString("stream","FAIL: native reply acceptance at "+suite.stage+" ("+error.getClass().getSimpleName()+(error instanceof AssertionError?": "+error.getMessage():"")+")\n");}
        finally{suite.cleanup();test.finish(code,result);}
    }
}
