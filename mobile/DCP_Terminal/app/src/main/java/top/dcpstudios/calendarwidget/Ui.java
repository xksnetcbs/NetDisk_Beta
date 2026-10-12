package top.dcpstudios.calendarwidget;

import android.app.Dialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.os.Build;
import android.provider.Settings;
import android.view.*;
import android.view.animation.DecelerateInterpolator;
import android.widget.*;

final class Ui {
 interface Selection { void accept(int index); }
 static final android.view.animation.Interpolator EASE=new android.view.animation.PathInterpolator(.23f,1f,.32f,1f);
 static void page(View view,String previous,String section){if(previous.equals(section)||!motion(view.getContext()))return;String order="focus home messages timetable";int from=order.indexOf(previous),to=order.indexOf(section);float direction=from>=0&&to>=0&&to<from?-1:1;view.setAlpha(.65f);view.setTranslationX(direction*16*view.getResources().getDisplayMetrics().density);view.animate().alpha(1).translationX(0).setDuration(220).setInterpolator(EASE).start();}
 static void resizeContent(LinearLayout content,Runnable change){
  if(content.getTag() instanceof android.animation.ValueAnimator)((android.animation.ValueAnimator)content.getTag()).cancel();
  int start=content.getHeight();change.run();
  if(!motion(content.getContext())||content.getWidth()==0)return;
  content.measure(View.MeasureSpec.makeMeasureSpec(content.getWidth(),View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));
  int end=content.getMeasuredHeight();android.view.ViewGroup.LayoutParams lp=content.getLayoutParams();lp.height=start;content.setLayoutParams(lp);
  android.animation.ValueAnimator animator=android.animation.ValueAnimator.ofInt(start,end);content.setTag(animator);animator.setDuration(220);animator.setInterpolator(EASE);
  animator.addUpdateListener(value->{lp.height=(Integer)value.getAnimatedValue();content.setLayoutParams(lp);});
  animator.addListener(new android.animation.AnimatorListenerAdapter(){public void onAnimationEnd(android.animation.Animator value){if(content.getTag()==value){lp.height=-2;content.setLayoutParams(lp);content.setTag(null);}}});animator.start();
 }
 static boolean motion(android.content.Context c){return Settings.Global.getFloat(c.getContentResolver(),Settings.Global.ANIMATOR_DURATION_SCALE,1)>0;}
 static void enter(View v,int delay){if(!motion(v.getContext()))return;v.animate().cancel();v.setAlpha(1);v.setTranslationY(24*v.getResources().getDisplayMetrics().density);v.animate().translationY(0).setStartDelay(0).setDuration(240).setInterpolator(EASE).start();}
 static void press(View v){v.setOnTouchListener((view,event)->{if(motion(view.getContext())){int action=event.getActionMasked();if(action==MotionEvent.ACTION_DOWN)view.animate().scaleX(.975f).scaleY(.975f).setDuration(90).start();else if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_CANCEL)view.animate().scaleX(1).scaleY(1).setDuration(160).start();}return false;});}
 static void divider(MainActivity a,LinearLayout parent){View v=new View(a);v.setBackgroundColor(a.line);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,a.d(1));p.topMargin=a.d(10);p.bottomMargin=a.d(10);parent.addView(v,p);}
 static void label(MainActivity a,LinearLayout parent,String title){TextView t=a.text(title,13,a.ink);t.setTypeface(null,Typeface.BOLD);t.setPadding(0,a.d(14),0,a.d(8));parent.addView(t);}
 static TextView row(MainActivity a,String text,int color){TextView t=a.text(text,13,color);t.setGravity(Gravity.CENTER_VERTICAL);t.setPadding(a.d(12),a.d(10),a.d(12),a.d(10));t.setMinHeight(a.d(44));return t;}
 static void select(MainActivity a,String title,String[] values,int selected,Selection action){
  Dialog dialog=new Dialog(a);LinearLayout box=a.column();box.setPadding(a.d(20),a.d(12),a.d(20),a.d(24));box.setBackground(a.bg(a.surface,20));View handle=new View(a);handle.setBackground(a.bg(a.line,2));LinearLayout.LayoutParams hp=new LinearLayout.LayoutParams(a.d(32),a.d(4));hp.gravity=Gravity.CENTER;hp.bottomMargin=a.d(16);box.addView(handle,hp);
  TextView heading=a.text(title,19,a.ink);heading.setTypeface(null,Typeface.BOLD);heading.setMinHeight(a.d(44));heading.setGravity(Gravity.CENTER_VERTICAL);box.addView(heading);sheet(heading,box,dialog);a.space(box,12);ScrollView scroll=new ScrollView(a);LinearLayout options=a.column();scroll.addView(options);
  for(int i=0;i<values.length;i++){final int index=i;TextView row=row(a,values[i]+(selected==i?"  ✓":""),selected==i?a.accent:a.ink);a.touch(row,selected==i?(a.dark?0xFF243E3B:0xFFE4F0EB):a.surface);row.setOnClickListener(v->{dialog.dismiss();action.accept(index);});press(row);options.addView(row,new LinearLayout.LayoutParams(-1,-2));if(i<values.length-1){View line=new View(a);line.setBackgroundColor(a.line);options.addView(line,new LinearLayout.LayoutParams(-1,a.d(1)));}}
  box.addView(scroll,new LinearLayout.LayoutParams(-1,Math.min(a.d(values.length*48),a.getResources().getDisplayMetrics().heightPixels/2)));Button cancel=a.button("关闭",dialog::dismiss);box.addView(cancel);dialog.setContentView(box);Window w=dialog.getWindow();if(w!=null){w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.28f);w.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setGravity(Gravity.BOTTOM);w.setLayout(-1,-2);w.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);}dialog.show();if(w!=null)w.setLayout(-1,-2);enter(box,0);
 }
 static void sheet(View handle,View box,Dialog dialog){Motion spring=new Motion(box);handle.setOnTouchListener(new View.OnTouchListener(){float down,origin;android.view.VelocityTracker tracker;
  public boolean onTouch(View view,MotionEvent e){int action=e.getActionMasked();if(action==MotionEvent.ACTION_DOWN){if(tracker!=null)tracker.recycle();tracker=android.view.VelocityTracker.obtain();down=e.getRawY();box.animate().cancel();spring.stop();origin=box.getTranslationY();}
   if(tracker!=null)tracker.addMovement(e);
   if(action==MotionEvent.ACTION_MOVE){float y=origin+e.getRawY()-down;box.setTranslationY(y>=0?y:Motion.resist(y,24));}
   if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_CANCEL){float velocity=0;if(tracker!=null){tracker.computeCurrentVelocity(1000);velocity=tracker.getYVelocity();tracker.recycle();tracker=null;}boolean close=action==MotionEvent.ACTION_UP&&velocity>-150&&box.getTranslationY()+velocity*.12f>box.getHeight()*.25f;
    if(close)box.animate().translationY(box.getHeight()).alpha(0).setDuration(motion(box.getContext())?180:0).withEndAction(dialog::dismiss).start();else spring.home(0,velocity);}
   return true;
  }});}
 static final class Choice extends LinearLayout {
  final MainActivity a;final String[] labels;final java.util.List<TextView> items=new java.util.ArrayList<>();int selected;Selection listener;
  Choice(MainActivity a,String[] labels,int selected,int columns){super(a);this.a=a;this.labels=labels;this.selected=Math.max(0,selected);setOrientation(VERTICAL);setPadding(0,a.d(3),0,a.d(6));
   for(int start=0;start<labels.length;start+=columns){LinearLayout row=new LinearLayout(a);for(int j=0;j<columns;j++){int n=start+j;LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1);p.setMargins(a.d(2),a.d(2),a.d(2),a.d(2));if(n>=labels.length){row.addView(new View(a),p);continue;}TextView t=a.text(labels[n],12,a.ink);t.setGravity(Gravity.CENTER);t.setMinHeight(a.d(38));t.setPadding(a.d(5),a.d(8),a.d(5),a.d(8));t.setMaxLines(2);t.setContentDescription(labels[n]);final int index=n;t.setOnClickListener(v->{this.selected=index;paint();if(listener!=null)listener.accept(index);});press(t);items.add(t);row.addView(t,p);}addView(row,new LinearLayout.LayoutParams(-1,-2));}paint();
  }
  void paint(){for(int i=0;i<items.size();i++){TextView t=items.get(i);boolean on=i==selected,changed=t.isSelected()!=on;t.setSelected(on);t.setTextColor(on?Color.WHITE:a.muted);t.setTypeface(null,on?Typeface.BOLD:Typeface.NORMAL);a.touch(t,on?a.accent:(a.dark?0xFF25282D:0xFFEDF0F2));if(changed&&t.isLaidOut()&&motion(a)){t.setAlpha(.55f);t.animate().alpha(1).setDuration(180).start();}}}
  int getSelectedItemPosition(){return selected;}
  void onChange(Selection value){listener=value;}
 }
}
