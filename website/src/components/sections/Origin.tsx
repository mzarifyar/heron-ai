'use client'

import { motion, useInView } from 'framer-motion'
import { useRef } from 'react'
import { HeronMark } from '../Logo'

export default function Origin() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })

  return (
    <section id="origin" className="py-32 relative overflow-hidden" ref={ref}>
      {/* Dark section */}
      <div className="absolute inset-0 bg-zinc-900/50" />

      {/* Large faded heron watermark */}
      <div className="absolute right-0 top-1/2 -translate-y-1/2 opacity-[0.03] pointer-events-none">
        <HeronMark size={520} />
      </div>

      <div className="relative max-w-4xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.8 }}
        >
          <p className="text-sm font-mono text-violet-400 tracking-widest uppercase mb-8">Our name</p>

          <div className="flex items-start gap-6 mb-10">
            <div className="shrink-0 opacity-80">
              <HeronMark size={56} />
            </div>
            <div>
              <h2 className="text-5xl md:text-6xl font-black tracking-tight text-zinc-100 leading-tight">
                Named after<br />
                <span className="gradient-text">the first engineer</span><br />
                of autonomous machines.
              </h2>
            </div>
          </div>

          <div className="space-y-6 text-lg text-zinc-400 leading-relaxed border-l-2 border-violet-500/30 pl-8">
            <p>
              <em className="text-zinc-300">Alexandria, Egypt. Circa 60 AD.</em>
            </p>
            <p>
              In the great city of Alexandria, a mathematician named Heron spent his life solving
              a single problem: <strong className="text-zinc-200">how do you make a system act on its own?</strong>
            </p>
            <p>
              He built doors that opened automatically when a signal was detected — heat from a
              temple altar triggering a chain of mechanisms no human hand had to touch. He built the
              world&apos;s first coin-operated vending machine. A programmable cart that followed a
              preset route. A wind-powered organ. Every machine shared the same soul:
              <em className="text-violet-300"> observe a signal, respond without hesitation, complete the loop.</em>
            </p>
            <p>
              His writings — the <em>Pneumatica</em>, the <em>Automata</em>, the <em>Mechanica</em> —
              were copied, translated, passed from Arabic scholars to European engineers, and formed
              the intellectual bedrock of the Industrial Revolution. Watt&apos;s steam governor.
              The thermostat. The autopilot. Every self-regulating machine that followed owed
              something to the workshop in Alexandria.
            </p>
            <p>
              Heron died leaving no grand monuments. What he left was a way of thinking:
              that a well-designed system should not need a human standing over it, waiting
              for something to go wrong.
            </p>
          </div>

          <motion.blockquote
            initial={{ opacity: 0 }}
            animate={inView ? { opacity: 1 } : {}}
            transition={{ delay: 0.6, duration: 0.8 }}
            className="mt-12 pl-8 border-l-2 border-violet-500"
          >
            <p className="text-2xl font-semibold text-zinc-200 italic leading-relaxed">
              &ldquo;This platform carries his name because it carries his idea. When Heron resolves
              an incident at 3 AM before anyone wakes up, it is doing exactly what the engineer
              in Alexandria spent his life trying to prove was possible.&rdquo;
            </p>
            <footer className="mt-4 text-sm text-zinc-500">
              — from the Heron dedication
            </footer>
          </motion.blockquote>

          <motion.p
            initial={{ opacity: 0 }}
            animate={inView ? { opacity: 1 } : {}}
            transition={{ delay: 0.9 }}
            className="mt-12 text-xl font-semibold gradient-text"
          >
            The loop closes itself. It always has.
          </motion.p>
        </motion.div>
      </div>
    </section>
  )
}
