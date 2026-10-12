package top.dcpstudios.calendarwidget;

import android.view.View;
import androidx.dynamicanimation.animation.DynamicAnimation;
import androidx.dynamicanimation.animation.SpringAnimation;
import androidx.dynamicanimation.animation.SpringForce;

/** Re-targetable native spring; a fresh press can take over its current position. */
final class Motion {
 final SpringAnimation x,y;
 final View view;
 Motion(View view){this.view=view;x=spring(view,DynamicAnimation.TRANSLATION_X);y=spring(view,DynamicAnimation.TRANSLATION_Y);view.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener(){public void onViewAttachedToWindow(View v){}public void onViewDetachedFromWindow(View v){stop();}});}
 static SpringAnimation spring(View view,DynamicAnimation.ViewProperty property){SpringAnimation animation=new SpringAnimation(view,property);animation.setSpring(new SpringForce(0).setStiffness(650).setDampingRatio(1));return animation;}
 void stop(){x.cancel();y.cancel();}
 void home(float vx,float vy){if(!Ui.motion(view.getContext())){stop();view.setTranslationX(0);view.setTranslationY(0);return;}x.setStartVelocity(vx).animateToFinalPosition(0);y.setStartVelocity(vy).animateToFinalPosition(0);}
 static float resist(float delta,float limit){return delta*limit/(limit+Math.abs(delta));}
}
