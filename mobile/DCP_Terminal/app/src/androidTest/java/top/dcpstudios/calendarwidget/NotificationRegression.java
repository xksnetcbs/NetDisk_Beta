package top.dcpstudios.calendarwidget;
import android.content.Context;
import org.json.JSONObject;
final class NotificationRegression {
    static void run(TerminalIntegrationInstrumentation test, Context context) throws Exception {
        NetDiskRaceRegression.identity(test, context, true);
        android.content.SharedPreferences prefs = TerminalClient.prefs(context);
        String previous = prefs.getString("error", ""); long since = prefs.getLong("error_since", 0), seen = prefs.getLong("cards_seen", 0);
        prefs.edit().putString("error", "消息连接不及时").putLong("error_since", System.currentTimeMillis() + 10000).putLong("cards_seen", 0).commit();
        test.check(AttentionCards.cards(context).stream().noneMatch(card -> card.title.contains("连接") || card.body.contains("不及时")), "connection lag never creates an urgent notification card");
        TerminalDb.get(context).put(new JSONObject().put("id", 982345).put("source", "canvas").put("title", "Real coursework notification").put("body", "New assignment").put("notify", true).put("is_read", false).put("occurred_at", System.currentTimeMillis()));
        test.check(AttentionCards.cards(context).stream().anyMatch(card -> card.message == 982345), "removing connection warnings retains actual coursework message reminders");
        TerminalDb.get(context).getWritableDatabase().delete("messages", "id=?", new String[]{"982345"});
        android.content.SharedPreferences.Editor restore = prefs.edit().putLong("cards_seen", seen); if (previous.isEmpty()) restore.remove("error"); else restore.putString("error", previous); if (since == 0) restore.remove("error_since"); else restore.putLong("error_since", since); restore.commit();
        NetDiskSession.observeWebLogin(context, true);
    }
}
