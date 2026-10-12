package top.dcpstudios.calendarwidget;

import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;

final class ConversationScreen {
 final MainActivity a;final JSONObject anchor;final TreeMap<String,JSONObject> rows=new TreeMap<>();
 LinearLayout list;ScrollView scroll;Button older;String before="";boolean busy=false;final String chat;
 MessageReply replyBar;
 ConversationScreen(MainActivity a,JSONObject anchor){this.a=a;this.anchor=anchor;JSONObject payload=anchor.optJSONObject("payload");chat=payload==null?"":payload.optString("chat_id");}
 void show(){
  a.base("conversation_history");a.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
  a.root.addView(a.button("‹ 返回消息",a::messages));a.screenTitle(anchor.optString("title"),"会话历史 · 按发送时间排列");
  older=a.button("载入更早的消息",()->load(true));a.root.addView(older);scroll=new ScrollView(a);list=a.column();scroll.addView(list);a.root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
  replyBar=MessageReply.mount(a,anchor,()->{load(false);list.postDelayed(()->{if(attached())load(false);},3500);});
  if(chat.isEmpty()){local();older.setVisibility(View.GONE);}else scroll.post(()->load(false));
 }
 boolean attached(){return "conversation_history".equals(a.page)&&list.isAttachedToWindow();}
 void local(){List<JSONObject> data=TerminalDb.get(a).messages("");Collections.sort(data,(x,y)->Long.compare(x.optLong("occurred_at"),y.optLong("occurred_at")));MessageScreen helper=new MessageScreen(a);String key=helper.key(anchor);for(JSONObject row:data)if(key.equals(helper.key(row)))bubble(row.optString("body"),helper.sender(row),row.optLong("occurred_at"),false,VisualStyles.message(row));}
 void load(boolean more){
  if(busy||!attached())return;final NetDiskSession.Account account;
  try{account=NetDiskSession.account(a);}catch(Exception ignored){return;}
  busy=true;older.setEnabled(false);older.setText("载入中…");String cursor=more?before:"";int oldHeight=list.getHeight(),oldScroll=scroll.getScrollY();
  TerminalClient.IO.execute(()->{try{
   JSONObject page=TerminalClient.requestBound(a,"/desktop/messages?limit=80&chat="+android.net.Uri.encode(chat)+(cursor.isEmpty()?"":"&before="+android.net.Uri.encode(cursor)),null,account).data;
   NetDiskSession.ui(a,account,()->{if(!attached())return;JSONArray items=page.optJSONArray("items");if(!more&&replyBar!=null)replyBar.history(items);if(items!=null)for(int i=0;i<items.length();i++){JSONObject m=items.optJSONObject(i);if(m!=null)rows.put(String.format(Locale.US,"%020d:%020d",m.optLong("time"),m.optLong("id")),m);}before=page.optString("before","");list.removeAllViews();
    for(JSONObject m:rows.values()){String body=m.optString("text");JSONObject file=m.optJSONObject("attachment");if(file!=null)body="[文件] "+file.optString("name");bubble(body,m.optString("sender"),m.optLong("time")*1000,m.optBoolean("outgoing"),VisualStyles.message(anchor));}
    older.setVisibility(page.optBoolean("more")?View.VISIBLE:View.GONE);scroll.post(()->{try{NetDiskSession.guard(a,account,()->{if(attached())scroll.scrollTo(0,more?oldScroll+list.getHeight()-oldHeight:list.getHeight());});}catch(Exception ignored){}});
   });
  }catch(Exception e){NetDiskSession.ui(a,account,()->{if(attached())Toast.makeText(a,"历史载入失败："+e.getMessage(),Toast.LENGTH_LONG).show();});}
  finally{NetDiskSession.ui(a,account,()->{if(attached()){busy=false;older.setEnabled(true);older.setText("载入更早的消息");}});}});
 }
 void bubble(String text,String sender,long time,boolean own,String category){LinearLayout lane=new LinearLayout(a);lane.setGravity(own?Gravity.RIGHT:Gravity.LEFT);LinearLayout card=a.column();card.setPadding(a.d(12),a.d(9),a.d(12),a.d(10));VisualStyles.apply(a,card,own?"我发送的":category);TextView meta=a.text((own?"我":sender)+" · "+new java.text.SimpleDateFormat("M/d HH:mm",Locale.CHINA).format(new Date(time)),10,a.muted);card.addView(meta);TextView body=a.text(text,14,a.ink);body.setTextIsSelectable(true);body.setPadding(0,a.d(5),0,0);card.addView(body);LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-1,-2);cp.leftMargin=own?a.d(28):0;cp.rightMargin=own?0:a.d(28);lane.addView(card,cp);LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.bottomMargin=a.d(10);list.addView(lane,lp);}
}
