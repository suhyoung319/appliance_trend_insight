import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Login from './pages/Login'
import SignUp from './pages/SignUp'
import B2CDashboard from './pages/B2CDashboard'
import B2BDashboard from './pages/B2BDashboard'
import MyPage from './pages/MyPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<SignUp />} />
      <Route path="/b2c" element={<B2CDashboard />} />
      <Route path="/b2b" element={<B2BDashboard />} />
      <Route path="/mypage" element={<MyPage />} />
    </Routes>
  )
}