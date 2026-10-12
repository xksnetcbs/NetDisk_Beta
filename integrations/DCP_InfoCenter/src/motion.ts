import type { ObjectDirective } from 'vue'
import { gsap } from 'gsap'
import { Draggable } from 'gsap/Draggable'
import { InertiaPlugin } from 'gsap/InertiaPlugin'

gsap.registerPlugin(Draggable, InertiaPlugin)
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches
const contexts = new WeakMap<HTMLElement, gsap.Context>()
export const vMotion: ObjectDirective<HTMLElement> = {
  mounted(el) {
    if (reduced()) return
    contexts.set(el, gsap.context(() => {
      gsap.fromTo(el, { opacity: 0, y: 7 }, { opacity: 1, y: 0, duration: .22, ease: 'power2.out', clearProps: 'opacity,transform' })
    }, el))
  },
  unmounted(el) { contexts.get(el)?.revert(); contexts.delete(el) },
}

type Swipe = { axis: 'x' | 'y'; trigger: string; close: () => void }
const gestures = new WeakMap<HTMLElement, { mm: gsap.MatchMedia; options: Swipe }>()
export const vSwipe: ObjectDirective<HTMLElement, Swipe> = {
  mounted(el, binding) {
    const state = { mm: gsap.matchMedia(), options: binding.value }
    gestures.set(el,state)
    state.mm.add('(max-width: 720px)', () => {
      const axis = state.options.axis
      let commit = false
      const distance = () => axis === 'x' ? el.clientWidth : el.clientHeight
      const [drag] = Draggable.create(el, {
        type: axis, trigger: el.querySelector(state.options.trigger) as HTMLElement,
        dragClickables: false, allowNativeTouchScrolling: true, minimumMovement: 9,
        bounds: axis === 'x' ? {minX:0,maxX:distance()} : {minY:0,maxY:distance()},
        edgeResistance: .85, inertia: true,
        snap: value => {
          const velocity = InertiaPlugin.getVelocity(el,axis)
          commit = value > Math.min(110,distance()*.3) && velocity > -150
          return commit ? distance() : 0
        },
        onPress() {
          commit=false; gsap.killTweensOf(el)
          this.applyBounds(axis === 'x' ? {minX:0,maxX:distance()} : {minY:0,maxY:distance()})
        },
        onDragEnd() {
          const event = this.pointerEvent as Event | undefined
          if(event?.type.includes('cancel')) { this.tween?.kill();commit=false;gsap.to(el,{[axis]:0,duration:reduced()?0:.2,ease:'power2.out'});return }
          if(reduced()) {this.tween?.progress(1)}
        },
        onThrowComplete() { if(commit)state.options.close();gsap.set(el,{clearProps:'transform'}) },
      })
      return () => { drag?.kill();gsap.killTweensOf(el);gsap.set(el,{clearProps:'transform'}) }
    })
  },
  updated(el,binding) { const state=gestures.get(el);if(state)state.options=binding.value },
  unmounted(el) { gestures.get(el)?.mm.revert();gestures.delete(el) },
}
