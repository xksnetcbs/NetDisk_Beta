package top.dcpstudios.calendarwidget;
import android.content.*;import android.graphics.Color;import android.widget.*;import java.util.*;
public class WidgetListService extends RemoteViewsService {
 public RemoteViewsFactory onGetViewFactory(Intent intent){return new Rows(getApplicationContext());}
 static final class Rows implements RemoteViewsFactory {
  final Context context;List<CalendarData.Event> rows=new ArrayList<>();Rows(Context c){context=c;}
  public void onCreate(){onDataSetChanged();}
  public void onDataSetChanged(){rows=CalendarData.visible(CalendarStore.read(context),System.currentTimeMillis(),CalendarStore.prefs(context).getBoolean("widgetDone",false),false);}
  public void onDestroy(){} public int getCount(){return rows.size();}
  public RemoteViews getViewAt(int p){
   if(p<0||p>=rows.size())return null;CalendarData.Event e=rows.get(p);RemoteViews v=new RemoteViews(context.getPackageName(),R.layout.widget_row);
   v.setTextViewText(R.id.row_title,(e.completed?"✓  ":"○  ")+e.title);
   v.setTextViewText(R.id.row_subtitle,CalendarData.timing(e,System.currentTimeMillis())+" · "+CalendarData.format(e.due));
   v.setTextColor(R.id.row_title,e.completed?AttentionCards.muted(context):AttentionCards.ink(context));
   v.setTextColor(R.id.row_subtitle,!e.completed&&e.due>0&&e.due<System.currentTimeMillis()?(AttentionCards.dark(context)?0xFFFFB6A1:0xFFA14832):AttentionCards.muted(context));
   v.setOnClickFillInIntent(R.id.widget_row,new Intent().putExtra("uid",e.uid));return v;
  }
  public RemoteViews getLoadingView(){return null;} public int getViewTypeCount(){return 1;} public long getItemId(int p){return rows.get(p).uid.hashCode();} public boolean hasStableIds(){return false;}
 }
}
