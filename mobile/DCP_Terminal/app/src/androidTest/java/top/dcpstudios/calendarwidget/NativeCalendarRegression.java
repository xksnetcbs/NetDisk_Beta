package top.dcpstudios.calendarwidget;
import android.content.Context;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.TimeUnit;
/** Verifies server overrides, installed-version migration and delayed account writes. */
final class NativeCalendarRegression {
    static void run(TerminalIntegrationInstrumentation test,Context c)throws Exception{
        NetDiskRaceRegression.identity(test,c,false);NetDiskTransportRegression.forced=false;NetDiskTransportRegression.sourceCompleted=false;
        CalendarStore.prefs(c).edit().putBoolean("force:netdisk:task:11",true).putBoolean("force:unknown-legacy-uid",true).commit();int before=NetDiskTransportRegression.forceWrites;
        TerminalClient.sync(c,false);
        test.check(NetDiskTransportRegression.forceWrites==before+1&&!CalendarStore.prefs(c).contains("force:netdisk:task:11")&&CalendarStore.prefs(c).contains("force:unknown-legacy-uid"),"installed 1.5.0 force markers migrate only visible current-account UIDs and clear after server ACK");
        test.check(CalendarStore.read(c).get(0).forcedCompleted&&CalendarStore.read(c).get(0).completed,"server forced completion is rendered after local marker removal");
        CalendarStore.prefs(c).edit().putBoolean("force:netdisk:task:11",false).commit();TerminalClient.sync(c,false);
        test.check(!CalendarStore.read(c).get(0).completed&&!CalendarStore.read(c).get(0).forcedCompleted,"false cancellation migrates and restores an unfinished source schedule");
        NetDiskTransportRegression.sourceCompleted=true;TerminalClient.sync(c,false);
        test.check(CalendarStore.read(c).get(0).completed&&!CalendarStore.read(c).get(0).forcedCompleted,"cancelling a personal override preserves natural server completion");
        NetDiskTransportRegression.sourceCompleted=false;NetDiskTransportRegression.forceOffline=true;CalendarStore.prefs(c).edit().putBoolean("force:netdisk:task:11",true).commit();boolean offline=false;
        try{TerminalClient.sync(c,false);}catch(java.io.IOException expected){offline=true;}
        test.check(offline&&TaskOverrides.pending(c,"netdisk:task:11")&&CalendarStore.read(c).get(0).forcedCompleted,"offline force intent survives in persistent pending state for retry");
        NetDiskTransportRegression.forceOffline=false;TerminalClient.sync(c,false);test.check(!TaskOverrides.pending(c,"netdisk:task:11")&&CalendarStore.read(c).get(0).forcedCompleted,"pending force retry becomes authoritative server state");
        CalendarStore.prefs(c).edit().putBoolean("force:netdisk:task:11",false).commit();NetDiskSession.Account old=NetDiskSession.account(c);NetDiskTransportRegression.delay("/api/mobile/terminal/schedules/netdisk:task:11");AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread worker=new Thread(()->{try{TaskOverrides.flush(c,old);}catch(Throwable error){failure.set(error);}});worker.start();if(!NetDiskTransportRegression.entered.await(5,TimeUnit.SECONDS))throw new AssertionError("Force request did not enter delay");
        NetDiskSession.observeWebLogin(c,true);NetDiskTransportRegression.release.countDown();worker.join(5000);
        test.check(!worker.isAlive()&&failure.get() instanceof NetDiskSession.AccountChanged&&!CalendarStore.prefs(c).contains("force:netdisk:task:11")&&TerminalDb.get(c).schedules().isEmpty(),"late force ACK cannot recreate data or pending state after logout");
        NetDiskTransportRegression.forced=false;
    }
}
