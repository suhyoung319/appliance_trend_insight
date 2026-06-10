import Navbar from '../components/common/Navbar'
import Hero from '../components/sections/Hero'
import DataSources from '../components/sections/DataSources'
import ReportPreview from '../components/sections/ReportPreview'

export default function Home() {
  return (
    <>
      <Navbar />
      <main>
        <Hero />

        {/* 섹션 구분선 */}
        <div style={{ height: '1px', background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.07), transparent)', margin: '0 48px' }} />

        <DataSources />

        <div style={{ height: '1px', background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.07), transparent)', margin: '0 48px' }} />

        <ReportPreview />
      </main>
    </>
  )
}
