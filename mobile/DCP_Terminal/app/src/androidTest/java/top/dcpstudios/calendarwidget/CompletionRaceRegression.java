package top.dcpstudios.calendarwidget;

import android.content.Context;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Foreground sync and UI completion retries must preserve the latest intent. */
final class CompletionRaceRegression {
    static void run(TerminalIntegrationInstrumentation test,Context c)throws Exception{
        NetDiskRaceRegression.identity(test,c,false);
        NetDiskTransportRegression.forced=false;
        NetDiskTransportRegression.sourceCompleted=false;
        NetDiskTransportRegression.forceOffline=false;
        final String uid="netdisk:task:11",key="force:"+uid,pending="force_pending:"+uid;
        NetDiskSession.Account account=NetDiskSession.account(c);
        CalendarStore.prefs(c).edit().putBoolean(key,true).putLong(pending,101).commit();
        NetDiskTransportRegression.delay("/api/mobile/terminal/schedules/"+uid);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        AtomicBoolean oldAckKeptNewIntent=new AtomicBoolean();
        CountDownLatch newerStarted=new CountDownLatch(1);
        int before=NetDiskTransportRegression.forceWrites;
        // TerminalClient.sync holds this monitor in the stream and job workers.
        Thread older=new Thread(()->{try{synchronized(TerminalClient.class){
            TaskOverrides.flush(c,account);
            oldAckKeptNewIntent.set(CalendarStore.prefs(c).contains(key)
                &&!CalendarStore.prefs(c).getBoolean(key,true)
                &&CalendarStore.prefs(c).getLong(pending,0)==102
                &&!CalendarStore.read(c).get(0).forcedCompleted);
        }}catch(Throwable error){failure.compareAndSet(null,error);}},"old-force-sync-fixture");
        Thread newer=new Thread(()->{newerStarted.countDown();try{TaskOverrides.flush(c,account);}
            catch(Throwable error){failure.compareAndSet(null,error);}},"new-force-ui-fixture");
        try{
            older.start();
            if(!NetDiskTransportRegression.entered.await(5,TimeUnit.SECONDS))throw new AssertionError("Old completion did not enter delay");
            // The user's new cancellation is saved while the old true is in flight.
            NetDiskSession.guard(c,account,()->CalendarStore.prefs(c).edit().putBoolean(key,false).putLong(pending,102).commit());
            newer.start();
            if(!newerStarted.await(5,TimeUnit.SECONDS))throw new AssertionError("New completion worker did not start");
            long deadline=android.os.SystemClock.elapsedRealtime()+2000;
            while(newer.getState()!=Thread.State.BLOCKED&&android.os.SystemClock.elapsedRealtime()<deadline)Thread.sleep(10);
            test.check(newer.getState()==Thread.State.BLOCKED&&NetDiskTransportRegression.forceWrites==before,
                "UI cancellation waits for the older foreground completion request instead of racing its server write");
            NetDiskTransportRegression.release.countDown();
            older.join(5000);newer.join(5000);
            if(older.isAlive()||newer.isAlive())throw new AssertionError("Completion workers did not finish");
            if(failure.get()!=null)throw new AssertionError("Completion worker failed",failure.get());
            test.check(oldAckKeptNewIntent.get(),"old true ACK preserves the newer false pending intent and its visible unfinished state");
            test.check(NetDiskTransportRegression.forceWrites==before+2&&!NetDiskTransportRegression.forced
                &&!CalendarStore.prefs(c).contains(key)&&!CalendarStore.prefs(c).contains(pending)
                &&!CalendarStore.read(c).get(0).forcedCompleted&&!CalendarStore.read(c).get(0).completed,
                "new false ACK is the final server and cached completion state after pending markers clear");
        }finally{
            NetDiskTransportRegression.release.countDown();
            older.join(5000);if(newer.getState()!=Thread.State.NEW)newer.join(5000);
            NetDiskTransportRegression.delayPath=null;
            NetDiskSession.observeWebLogin(c,true);
        }
    }
}
