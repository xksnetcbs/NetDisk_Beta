package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.view.*;
import android.widget.FrameLayout;

/** Horizontal card paging leaves vertical gestures and child buttons untouched. */
final class SwipeCards extends FrameLayout {
 interface Page { void change(int direction); }
 final Page page;final int slop;float downX,downY,start;View foreground;Motion spring;VelocityTracker velocity;
 boolean dragging;
 SwipeCards(Context context,Page page){super(context);this.page=page;slop=ViewConfiguration.get(context).getScaledTouchSlop();setClipChildren(true);}
 public boolean onInterceptTouchEvent(MotionEvent e){
  if(e.getActionMasked()==MotionEvent.ACTION_DOWN){recycle();downX=e.getX();downY=e.getY();View current=getChildCount()==0?null:getChildAt(getChildCount()-1);if(spring!=null)spring.stop();if(current!=foreground){foreground=current;spring=current==null?null:new Motion(current);}if(foreground!=null)start=foreground.getTranslationX();velocity=VelocityTracker.obtain();velocity.addMovement(e);dragging=false;}
  if(e.getActionMasked()==MotionEvent.ACTION_MOVE&&foreground!=null){float dx=e.getX()-downX,dy=e.getY()-downY;if(Math.abs(dx)>slop&&Math.abs(dx)>Math.abs(dy)*1.4f){dragging=true;getParent().requestDisallowInterceptTouchEvent(true);return true;}}
  if(e.getActionMasked()==MotionEvent.ACTION_CANCEL||e.getActionMasked()==MotionEvent.ACTION_UP){if(spring!=null)spring.home(0,0);recycle();}
  return false;
 }
 public boolean onTouchEvent(MotionEvent e){if(foreground==null)return false;if(velocity==null)velocity=VelocityTracker.obtain();velocity.addMovement(e);
  if(e.getActionMasked()==MotionEvent.ACTION_MOVE){foreground.setTranslationX(Motion.resist(start+e.getX()-downX,getWidth()));return true;}
  if(e.getActionMasked()==MotionEvent.ACTION_UP||e.getActionMasked()==MotionEvent.ACTION_CANCEL){velocity.computeCurrentVelocity(1000);float speed=velocity.getXVelocity(),projected=foreground.getTranslationX()+speed*.1f;boolean commit=e.getActionMasked()==MotionEvent.ACTION_UP&&Math.abs(projected)>getWidth()*.23f;
   if(commit){performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK);page.change(projected<0?1:-1);}else spring.home(speed,0);dragging=false;recycle();return true;}
  return true;
 }
 private void recycle(){if(velocity!=null){velocity.recycle();velocity=null;}}
 boolean interacting(){return velocity!=null;}
 protected void onDetachedFromWindow(){if(spring!=null)spring.stop();recycle();super.onDetachedFromWindow();}
}
