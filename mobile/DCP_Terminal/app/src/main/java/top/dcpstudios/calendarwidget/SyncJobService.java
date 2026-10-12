package top.dcpstudios.calendarwidget;
import android.app.job.*;import android.content.*;import java.util.concurrent.*;
/** System-owned jobs survive process eviction; widget broadcasts never own network threads. */
public class SyncJobService extends JobService {
 static final int PERIODIC=2101,IMMEDIATE=2102;
 static final ExecutorService EXECUTOR=Executors.newSingleThreadExecutor();
 static final class Run {volatile boolean cancelled;Future<?> future;}
 private final java.util.Map<Integer,Run> runs=new java.util.HashMap<>();
 public static void schedule(Context c,boolean now){
  JobScheduler s=(JobScheduler)c.getSystemService(JOB_SCHEDULER_SERVICE);ComponentName component=new ComponentName(c,SyncJobService.class);int minutes=CalendarStore.prefs(c).getInt("interval",30);
  if(minutes==0)s.cancel(PERIODIC);else{JobInfo current=pending(s,PERIODIC);if(current==null||current.getIntervalMillis()!=minutes*60000L)s.schedule(new JobInfo.Builder(PERIODIC,component).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPersisted(true).setPeriodic(minutes*60000L).build());}
  if(now)s.schedule(new JobInfo.Builder(IMMEDIATE,component).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setOverrideDeadline(0).build());
 }
 static JobInfo pending(JobScheduler s,int id){for(JobInfo job:s.getAllPendingJobs())if(job.getId()==id)return job;return null;}
 public boolean onStartJob(JobParameters p){
  Run run=new Run();runs.put(p.getJobId(),run);
  run.future=EXECUTOR.submit(()->{boolean failed=false;try{TerminalClient.sync(this,true);}catch(Exception e){TerminalClient.prefs(this).edit().putString("error","消息后台同步失败，等待重试").apply();failed=true;}try{CalendarStore.sync(this);}catch(Exception e){failed=true;}
   if(!run.cancelled)CalendarWidget.renderAll(this);final boolean retry=failed;
   new android.os.Handler(getMainLooper()).post(()->{if(!run.cancelled){runs.remove(p.getJobId());jobFinished(p,retry);}});
  });return true;
 }
 public boolean onStopJob(JobParameters p){Run run=runs.remove(p.getJobId());if(run!=null){run.cancelled=true;if(run.future!=null)run.future.cancel(true);}return true;}
}
