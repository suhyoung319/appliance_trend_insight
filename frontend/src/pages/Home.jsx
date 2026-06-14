// Home.jsx
import { useState } from 'react'
import Navbar from '../components/common/Navbar'
import Hero from '../components/sections/Hero'
import DataSources from '../components/sections/DataSources'
import ReportPreview from '../components/sections/ReportPreview'

export default function Home() {
  const [mode, setMode] = useState('b2c')

  return (
    <>
      <Navbar mode={mode} setMode={setMode} />

      <main>
        <Hero mode={mode} />

        <div style={{ height: '1px', background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.07), transparent)', margin: '0 48px' }} />

        <DataSources mode={mode} />

        <div style={{ height: '1px', background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.07), transparent)', margin: '0 48px' }} />

        <ReportPreview mode={mode} />
      </main>
    </>
  )
}