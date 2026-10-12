package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.content.SharedPreferences;
import android.text.InputFilter;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** A fixed conversation target, an account-bound request and an honest send receipt. */
final class MessageReply {
    private static final ExecutorService IO = Executors.newSingleThreadExecutor();
    final MainActivity a;
    final NetDiskSession.Account account;
    final String source, chat, key;
    String uid;
    long probeEpoch;
    final Runnable onSent;
    final LinearLayout bar, chips;
    final TextView status;
    final EditText draft;
    final Button send, retry;
    boolean allowed, busy;
    int polls;

    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("message_reply", 0); }
    static void clearAccountData(Context c) { prefs(c).edit().clear().commit(); }

    static MessageReply mount(MainActivity a, JSONObject anchor, Runnable onSent) {
        JSONObject payload = anchor.optJSONObject("payload");
        String source = anchor.optString("source"), chat = payload == null ? "" : payload.optString("chat_id");
        String uid = anchor.optString("source_key", anchor.optString("uid"));
        if(uid.isEmpty() && payload!=null)uid=payload.optString("message_uid");
        if (chat.isEmpty() || !("netdisk".equals(source) || "wechat".equals(source) && "filehelper".equals(chat))) return null;
        if ("netdisk".equals(source) && (uid.isEmpty() || payload!=null && "system".equals(payload.optString("thread_type")))) return null;
        try { return new MessageReply(a, NetDiskSession.account(a), source, chat, uid, onSent); }
        catch (Exception ignored) { return null; }
    }

    private MessageReply(MainActivity a, NetDiskSession.Account account, String source, String chat, String uid, Runnable onSent) throws Exception {
        this.a = a; this.account = account; this.source = source; this.chat = chat; this.uid = uid; this.onSent = onSent;
        key = NetDiskSession.digest(account.origin + "\n" + account.userId + "\n" + source + "\n" + chat);
        NetDiskUi ui = new NetDiskUi(a);
        bar = a.column(); bar.setPadding(0, a.d(8), 0, 0); bar.setTag("message-reply");
        View divider = new View(a); divider.setBackgroundColor(a.line); bar.addView(divider, new LinearLayout.LayoutParams(-1, a.d(1)));
        status = ui.text("正在确认回复权限…", 12, a.muted, false); status.setPadding(0,a.d(7),0,a.d(3)); bar.addView(status);
        draft = ui.field("回复此会话…", false); draft.setTag("message-reply-draft"); draft.setSingleLine(false);
        draft.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        draft.setMinLines(1); draft.setMaxLines(3); draft.setFilters(new InputFilter[]{new InputFilter.LengthFilter(4000)});
        draft.setImeOptions(EditorInfo.IME_ACTION_SEND); draft.setOnEditorActionListener((v, action, event) -> { if(action==EditorInfo.IME_ACTION_SEND){act();return true;}return false; });
        chips = new LinearLayout(a);
        for (String text : new String[]{"收到", "好的", "谢谢"}) {
            Button chip = ui.button(text, null, () -> { draft.setText(text); draft.setSelection(draft.length()); });
            LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(0, a.d(44), 1); cp.rightMargin=a.d(5); chips.addView(chip, cp);
        }
        bar.addView(chips);
        LinearLayout composer = new LinearLayout(a); composer.setGravity(Gravity.CENTER_VERTICAL);
        composer.addView(draft, new LinearLayout.LayoutParams(0, -2, 1));
        send = ui.button("发送", null, this::act, true); send.setTag("message-reply-send");
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(a.d(88), a.d(48)); sp.leftMargin=a.d(8); composer.addView(send, sp); bar.addView(composer);
        retry = ui.button("重试同一请求", null, () -> { JSONObject pending=pending(); if(pending!=null) dispatch(pending, false); });
        retry.setTag("message-reply-retry"); retry.setVisibility(View.GONE); bar.addView(retry);
        a.root.addView(bar); controls(); probe();
    }

    boolean attached() { return bar.isAttachedToWindow() && "conversation_history".equals(a.page); }
    JSONObject pending() { try { String value=prefs(a).getString(key, ""); return value.isEmpty()?null:new JSONObject(value); } catch(Exception ignored){return null;} }
    private void save(JSONObject value) throws Exception { NetDiskSession.guard(a, account, () -> { if(!prefs(a).edit().putString(key,value.toString()).commit())throw new java.io.IOException("无法保存发送请求，请稍后重试"); }); }
    private void controls() {
        JSONObject pending=pending(); boolean locked=pending!=null;
        draft.setEnabled(allowed && !busy && !locked); for(int i=0;i<chips.getChildCount();i++)chips.getChildAt(i).setEnabled(allowed&&!busy&&!locked);
        send.setEnabled(allowed&&!busy); send.setText(busy?"处理中…":locked?("wechat".equals(source)?"检查状态":"重试发送"):"发送");
        retry.setVisibility(allowed && locked && "wechat".equals(source) ? View.VISIBLE : View.GONE); retry.setEnabled(!busy);
        if(pending!=null)draft.setText(pending.optString("text"));
    }

    private void probe() {
        final String messageUid=uid;
        final long epoch=++probeEpoch;
        IO.execute(() -> {
            try {
                JSONObject reply=TerminalClient.requestBound(a,"/replies/capabilities?source="+android.net.Uri.encode(source)+"&chat_id="+android.net.Uri.encode(chat)+"&message_uid="+android.net.Uri.encode(messageUid),null,account).data;
                NetDiskSession.ui(a,account,()->{ if(!attached()||epoch!=probeEpoch)return;allowed=reply.optBoolean("reply_enabled");
                    String reason=reply.optString("reason","此会话暂不能回复");
                    if("netdisk".equals(source)&&"站内会话来源不存在".equals(reason))reason="旧消息来源已失效；请返回消息列表刷新后打开最新消息";
                    status.setText(allowed?("wechat".equals(source)?"回复文件传输助手":"回复 NetDisk 站内会话"):reason);
                    JSONObject p=pending();if(allowed&&p!=null){
                        // The preference key and actor bind origin/user/source/chat.
                        // Rebind only after this current source passes server ACL;
                        // the request id and frozen text keep their original intent.
                        if("netdisk".equals(source)&&source.equals(p.optString("source"))&&chat.equals(p.optString("chat_id"))&&!messageUid.equals(p.optString("message_uid"))){
                            p.put("message_uid",messageUid);try{save(p);}catch(Exception failure){allowed=false;status.setText("无法保存当前发送请求，请重新打开会话重试");controls();return;}
                        }
                        status.setText(receiptText(p.optString("status","uncertain")));
                    }controls();
                });
            } catch(Exception e) { NetDiskSession.ui(a,account,()->{if(attached()&&epoch==probeEpoch){status.setText("暂时无法确认回复权限，请重新打开会话");controls();}}); }
        });
    }

    void history(JSONArray messages) {
        if(!"netdisk".equals(source)||messages==null||!attached())return;
        // A current authorized anchor keeps the draft and confirmed receipt stable.
        // Sending still checks the server ACL; pending requests need fresh proof.
        if(allowed&&pending()==null)return;
        String next="";long time=Long.MIN_VALUE,id=Long.MIN_VALUE;
        for(int i=0;i<messages.length();i++){
            JSONObject row=messages.optJSONObject(i);if(row==null||!source.equals(row.optString("source"))||!chat.equals(row.optString("chat_id")))continue;
            JSONObject payload=row.optJSONObject("payload");if(payload==null||!source.equals(payload.optString("source"))||!chat.equals(payload.optString("chat_id")))continue;
            String kind=payload.optString("thread_type"),candidate=row.optString("uid"),instance=payload.optString("instance_id");
            if(!("direct".equals(kind)||"project_group".equals(kind))||!instance.matches("[A-Za-z0-9_-]{1,64}")
                ||!candidate.matches("netdisk:"+instance+":(?:inbox|task_comment):[0-9]+")
                ||!candidate.equals(payload.optString("message_uid"))||!chat.startsWith("netdisk:"+instance+":"))continue;
            long stamp=row.optLong("time"),rowId=row.optLong("id");if(stamp>time||stamp==time&&rowId>id){next=candidate;time=stamp;id=rowId;}
        }
        if(next.isEmpty()||next.equals(uid))return;
        uid=next;allowed=false;status.setText("正在确认当前会话的回复权限…");controls();probe();
    }

    void act() {
        if(!allowed||busy||!attached())return;
        JSONObject pending=pending();
        if(pending!=null){dispatch(pending,"wechat".equals(source));return;}
        String text=draft.getText().toString();if(text.trim().isEmpty()){draft.setError("请输入回复内容");return;}
        try {
            JSONObject body=new JSONObject().put("id",UUID.randomUUID().toString()).put("source",source).put("chat_id",chat)
                .put("message_uid",uid).put("text",text).put("status","pending");
            save(body); dispatch(body,false);
        }catch(Exception e){a.error(e);}
    }

    private void dispatch(JSONObject pending, boolean check) {
        if(!allowed||busy||!attached())return;
        final String id=pending.optString("id");busy=true;status.setText(check?"正在核对发送回执…":"正在发送…");controls();
        IO.execute(()->{
            try {
                JSONObject result;
                if(check) result=TerminalClient.requestBound(a,"/replies/"+android.net.Uri.encode(id)+"/status",null,account).data;
                else { JSONObject body=new JSONObject(pending.toString());body.remove("status");result=TerminalClient.requestBound(a,"/replies/send",body,account).data; }
                String receipt=result.optString("status","uncertain");
                NetDiskSession.ui(a,account,()->finish(id,receipt,null));
            }catch(Exception e){NetDiskSession.ui(a,account,()->finish(id,"uncertain",e.getMessage()));}
        });
    }

    private void finish(String id,String receipt,String error) throws Exception {
        JSONObject current=pending(); if(current==null||!id.equals(current.optString("id")))return;
        if("confirmed".equals(receipt))prefs(a).edit().remove(key).commit();
        else {current.put("status",receipt);prefs(a).edit().putString(key,current.toString()).commit();}
        if(!attached())return;busy=false;
        status.setText(receiptText(receipt)+(error==null?"":" · "+error));
        if("confirmed".equals(receipt)){draft.setText("");onSent.run();}controls();
        if("wechat".equals(source)&&"submitted".equals(receipt)&&polls++<4)bar.postDelayed(()->{if(attached()&&!busy&&pending()!=null)act();},2500);
    }

    private String receiptText(String receipt) {
        if("confirmed".equals(receipt))return "发送成功";
        if("submitted".equals(receipt))return "已交给微信，等待发送回执";
        return "wechat".equals(source)?"发送结果待确认；可检查状态或用同一请求重试":"发送结果待确认；重试会沿用同一请求";
    }
}
