package top.dcpstudios.calendarwidget;

import android.content.*;import android.provider.Settings;import android.view.*;import android.widget.*;

/** Direct manipulation with a velocity-aware, interruptible critically damped spring. */
final class SwipeReadRow extends FrameLayout implements Choreographer.FrameCallback {
    private final View card;private final Runnable commit;private final int slop;
    private float downX,downY,origin,velocity,target;private long lastFrame;private boolean dragging,committing,animating;private VelocityTracker tracker;
    SwipeReadRow(Context c,View foreground,Runnable action,int hintColor){super(c);card=foreground;commit=action;slop=ViewConfiguration.get(c).getScaledTouchSlop();
        TextView hint=new TextView(c);hint.setText("✓  已读");hint.setTextSize(15);hint.setTextColor(hintColor);hint.setGravity(Gravity.END|Gravity.CENTER_VERTICAL);hint.setPadding(0,0,(int)(20*c.getResources().getDisplayMetrics().density),0);addView(hint,new LayoutParams(-1,-1));addView(card,new LayoutParams(-1,-2));
        setClipChildren(true);setClipToPadding(true);
    }
    public boolean onInterceptTouchEvent(android.view.MotionEvent e){switch(e.getActionMasked()){
        case MotionEvent.ACTION_DOWN:stop();downX=e.getX();downY=e.getY();origin=card.getTranslationX();dragging=false;tracker=VelocityTracker.obtain();tracker.addMovement(e);break;
        case MotionEvent.ACTION_MOVE:float dx=e.getX()-downX,dy=e.getY()-downY;if(Math.abs(dx)>slop&&Math.abs(dx)>Math.abs(dy)*1.3f){dragging=true;getParent().requestDisallowInterceptTouchEvent(true);return true;}break;
        case MotionEvent.ACTION_CANCEL:case MotionEvent.ACTION_UP:recycle();break;
    }return false;}
    public boolean onTouchEvent(MotionEvent e){if(tracker==null)tracker=VelocityTracker.obtain();tracker.addMovement(e);
        if(e.getActionMasked()==MotionEvent.ACTION_MOVE){float x=origin+e.getX()-downX;card.setTranslationX(x>0?x*.15f:Math.max(-getWidth(),x));return true;}
        if(e.getActionMasked()==MotionEvent.ACTION_UP||e.getActionMasked()==MotionEvent.ACTION_CANCEL){tracker.computeCurrentVelocity(1000);velocity=tracker.getXVelocity();boolean cancelled=e.getActionMasked()==MotionEvent.ACTION_CANCEL;
            float projected=card.getTranslationX()+velocity*.099f;committing=!cancelled&&velocity<400&&projected<-getWidth()*.28f;target=committing?-getWidth():0;recycle();settle();return true;}
        return true;
    }
    private void settle(){boolean reduced=Settings.Global.getFloat(getContext().getContentResolver(),Settings.Global.ANIMATOR_DURATION_SCALE,1)==0;
        if(reduced){card.setTranslationX(target);if(committing)commit.run();return;}animating=true;lastFrame=0;Choreographer.getInstance().postFrameCallback(this);}
    public void doFrame(long time){if(!animating)return;float delta=lastFrame==0?1f/60:Math.min(.032f,(time-lastFrame)/1e9f);lastFrame=time;float position=card.getTranslationX();float omega=24;
        velocity+=(-omega*omega*(position-target)-2*omega*velocity)*delta;position+=velocity*delta;card.setTranslationX(position);
        if(Math.abs(position-target)<.7f&&Math.abs(velocity)<8){card.setTranslationX(target);animating=false;if(committing){performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);commit.run();}}else Choreographer.getInstance().postFrameCallback(this);
    }
    private void stop(){animating=false;Choreographer.getInstance().removeFrameCallback(this);}
    private void recycle(){if(tracker!=null){tracker.recycle();tracker=null;}dragging=false;}
    protected void onDetachedFromWindow(){stop();recycle();super.onDetachedFromWindow();}
}
