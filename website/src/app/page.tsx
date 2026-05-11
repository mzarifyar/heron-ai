import Nav           from '../components/Nav'
import Hero          from '../components/sections/Hero'
import Problem       from '../components/sections/Problem'
import TheLoop       from '../components/sections/TheLoop'
import Chronicle     from '../components/sections/Chronicle'
import HowItWorks    from '../components/sections/HowItWorks'
import Integrations  from '../components/sections/Integrations'
import Origin        from '../components/sections/Origin'
import CTA           from '../components/sections/CTA'
import Footer        from '../components/Footer'

export default function Home() {
  return (
    <main>
      <Nav />
      <Hero />
      <Problem />
      <TheLoop />
      <Chronicle />
      <HowItWorks />
      <Integrations />
      <Origin />
      <CTA />
      <Footer />
    </main>
  )
}
