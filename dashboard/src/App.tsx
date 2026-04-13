import TodayPage from './pages/TodayPage'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-4 py-3">
        <h1 className="text-lg font-semibold tracking-wide">Soccer Picks</h1>
      </header>
      <main className="max-w-2xl mx-auto px-4 py-6">
        <TodayPage />
      </main>
    </div>
  )
}
