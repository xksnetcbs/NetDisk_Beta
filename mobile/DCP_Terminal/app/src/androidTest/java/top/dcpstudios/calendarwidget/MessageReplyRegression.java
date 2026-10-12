package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import org.json.JSONObject;
import org.json.JSONArray;
import java.util.concurrent.TimeUnit;

/** Real composer actions, durable same-id retry and rejection of a late account ACK. */
final class MessageReplyRegression {
    interface Condition { boolean ready(); }
    static void await(TerminalIntegrationInstrumentation test, Condition condition) throws Exception {
        for(int i=0;i<150;i++){test.waitForIdleSync();if(condition.ready())return;Thread.sleep(30);}
        throw new AssertionError("Message reply response did not finish");
    }
    static void tap(TerminalIntegrationInstrumentation test, View view) throws Exception {
        int[] location=new int[2];float[] point=new float[2];
        test.runOnMainSync(()->{if(!view.isShown()||view.getWidth()==0||view.getHeight()==0)throw new AssertionError("Reply control is not visible");view.getLocationOnScreen(location);point[0]=location[0]+view.getWidth()/2f;point[1]=location[1]+view.getHeight()/2f;});
        long now=SystemClock.uptimeMillis();MotionEvent down=MotionEvent.obtain(now,now,MotionEvent.ACTION_DOWN,point[0],point[1],0);
        try{test.sendPointerSync(down);}finally{down.recycle();}Thread.sleep(80);
        MotionEvent up=MotionEvent.obtain(now,SystemClock.uptimeMillis(),MotionEvent.ACTION_UP,point[0],point[1],0);
        try{test.sendPointerSync(up);}finally{up.recycle();}
        test.waitForIdleSync();
    }
    static void editorFocus(TerminalIntegrationInstrumentation test,EditText draft) throws Exception {
        InputMethodManager input=(InputMethodManager)test.getTargetContext().getSystemService(Context.INPUT_METHOD_SERVICE);
        await(test,()->draft.hasFocus()&&input.isAcceptingText());
    }
    static JSONObject anchor(String source,String chat) throws Exception {
        return new JSONObject().put("id",771).put("source",source).put("source_key","netdisk:test:inbox:771").put("title","Reply fixture")
            .put("payload",new JSONObject().put("chat_id",chat).put("message_uid","netdisk:test:inbox:771"));
    }
    static JSONObject history(String source,String chat,String uid,String kind,long time) throws Exception {
        return new JSONObject().put("id",time).put("source",source).put("uid",uid).put("chat_id",chat).put("time",time)
            .put("payload",new JSONObject().put("source","netdisk").put("instance_id","test").put("chat_id",chat).put("message_uid",uid).put("thread_type",kind));
    }
    static MessageReply show(TerminalIntegrationInstrumentation test,MainActivity a,String source,String chat) throws Exception {
        ConversationScreen screen=new ConversationScreen(a,anchor(source,chat));test.runOnMainSync(screen::show);
        MessageReply bar=screen.replyBar;if(bar!=null)await(test,()->bar.allowed);return bar;
    }
    static void run(TerminalIntegrationInstrumentation test,Context c) throws Exception {
        NetDiskRaceRegression.identity(test,c,true);
        test.activity=test.startActivitySync(new Intent(c,MainActivity.class).putExtra("page","messages").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        test.waitForIdleSync();MainActivity a=(MainActivity)test.activity;
        test.runOnMainSync(()->a.netdisk());
        MessageReply ordinary=show(test,a,"wechat","another-person");
        test.check(ordinary==null,"WeChat person and group messages have no reply composer");
        JSONObject system=anchor("netdisk","netdisk:test:system:user:44");system.getJSONObject("payload").put("thread_type","system");
        ConversationScreen notice=new ConversationScreen(a,system);test.runOnMainSync(notice::show);test.check(notice.replyBar==null,"system notices remain read-only without a disabled reply composer");
        JSONObject stale=anchor("netdisk","netdisk:test:thread:10");stale.put("source_key","netdisk:readonly:inbox:771");stale.getJSONObject("payload").put("message_uid","netdisk:readonly:inbox:771");
        ConversationScreen expired=new ConversationScreen(a,stale);test.runOnMainSync(expired::show);MessageReply old=expired.replyBar;
        await(test,()->!old.status.getText().toString().contains("确认回复权限"));test.check(!old.allowed&&!old.draft.isEnabled(),"an unavailable cached source cannot authorize editing or sending");
        JSONArray invalid=new JSONArray().put(history("wechat","netdisk:test:thread:10","netdisk:test:inbox:772","direct",10))
            .put(history("netdisk","netdisk:test:thread:20","netdisk:test:inbox:773","direct",11))
            .put(history("netdisk","netdisk:test:thread:10","netdisk:test:notification:774","system",12));
        test.runOnMainSync(()->old.history(invalid));test.check(!old.allowed&&"netdisk:readonly:inbox:771".equals(old.uid),"other sources, other conversations and system messages cannot replace a reply anchor");
        JSONArray refreshed=new JSONArray().put(history("netdisk","netdisk:test:thread:10","netdisk:test:inbox:772","direct",10))
            .put(history("netdisk","netdisk:test:thread:10","netdisk:test:notification:774","system",12));
        test.runOnMainSync(()->old.history(refreshed));await(test,()->old.allowed);
        test.check("netdisk:test:inbox:772".equals(old.uid)&&old.draft.isEnabled(),"real same-conversation history refreshes the stale source and server permission unlocks its editor");
        MessageReply bar=show(test,a,"netdisk","netdisk:test:thread:10");
        tap(test,bar.draft);editorFocus(test,bar.draft);test.runOnMainSync(()->test.check(bar.draft.isEnabled()&&bar.draft.hasFocus(),"authorized reply editor accepts an actual touch and receives keyboard focus"));
        test.sendStringSync("typed reply");test.runOnMainSync(()->{test.check("typed reply".contentEquals(bar.draft.getText()),"keyboard events enter text in the actual native reply editor");bar.draft.setText("");});
        test.runOnMainSync(()->{test.check(bar.send.getHeight()>=a.d(44)&&bar.chips.getChildAt(0).getHeight()>=a.d(44),"reply controls retain native touch targets");bar.chips.getChildAt(0).performClick();test.check("收到".contentEquals(bar.draft.getText()),"quick reply chip fills the native editor");bar.send.performClick();});
        await(test,()->!bar.busy&&bar.pending()==null);
        test.check(NetDiskTransportRegression.replyWrites>0&&"netdisk".equals(NetDiskTransportRegression.replyBody.optString("source")),"NetDisk send gets its real confirmed receipt and clears pending only after ACK");
        NetDiskTransportRegression.replyUncertain=true;
        test.runOnMainSync(()->{bar.draft.setText("same intent retry");bar.send.performClick();});await(test,()->!bar.busy&&bar.pending()!=null);
        String id=bar.pending().optString("id");
        MessageReply restored=show(test,a,"netdisk","netdisk:test:thread:10");
        test.check(id.equals(restored.pending().optString("id"))&&!restored.draft.isEnabled(),"reopening a conversation restores the same pending id and frozen text");
        JSONObject sameIntent=restored.pending();String frozen=sameIntent.getString("text");
        test.runOnMainSync(()->{try{restored.history(new JSONArray().put(history("netdisk","netdisk:test:thread:10","netdisk:test:inbox:772","direct",10)));}catch(Exception e){throw new RuntimeException(e);}});
        await(test,()->restored.allowed&&"netdisk:test:inbox:772".equals(restored.pending().optString("message_uid")));
        test.check(id.equals(restored.pending().optString("id"))&&frozen.equals(restored.pending().optString("text"))&&!restored.draft.isEnabled(),"a new authorized source rebinds pending proof while preserving its original id and frozen text");
        NetDiskTransportRegression.replyUncertain=false;test.runOnMainSync(()->restored.send.performClick());await(test,()->!restored.busy&&restored.pending()==null);
        test.check(id.equals(NetDiskTransportRegression.replyBody.optString("id"))&&"netdisk:test:inbox:772".equals(NetDiskTransportRegression.replyBody.optString("message_uid")),"manual NetDisk retry reuses the original request id with current authorized conversation proof");
        MessageReply helper=show(test,a,"wechat","filehelper");NetDiskTransportRegression.replyUncertain=true;
        test.runOnMainSync(()->{helper.draft.setText("self helper receipt fixture");helper.send.performClick();});await(test,()->!helper.busy&&helper.pending()!=null);
        int writes=NetDiskTransportRegression.replyWrites;test.runOnMainSync(()->helper.send.performClick());await(test,()->!helper.busy&&helper.pending()==null);
        test.check(writes==NetDiskTransportRegression.replyWrites,"uncertain filehelper action checks its existing receipt without another send");NetDiskTransportRegression.replyUncertain=false;
        MessageReply late=show(test,a,"netdisk","netdisk:test:thread:10");NetDiskTransportRegression.delay("/api/mobile/terminal/replies/send");
        test.runOnMainSync(()->{late.draft.setText("late account fixture");late.send.performClick();});
        if(!NetDiskTransportRegression.entered.await(5,TimeUnit.SECONDS))throw new AssertionError("Reply did not reach delayed transport");
        try{NetDiskRaceRegression.identity(test,c,false);}finally{NetDiskTransportRegression.release.countDown();}
        Thread.sleep(200);test.waitForIdleSync();
        test.check(MessageReply.prefs(c).getAll().isEmpty()&&!"conversation_history".equals(a.page),"account switch clears pending reply text and ignores late ACK UI/persistence");
        test.runOnMainSync(a::finish);test.activity=null;
    }
}
