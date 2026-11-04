import './App.css'
import UserUpload from './components/UserUpload'
import { useState } from 'react';
import Card from './components/Card';

function App() {
  const [uploadFinished, setUploadFinished] = useState(false);
  const [name, setName] = useState('test.pdf');

  const handleBlobName = (name) => {
    setName(name)
  }

  return (
    <div>
      <UserUpload 
        handleName={handleBlobName} 
        onUploadFinished={() => setUploadFinished(true)}/>
      {uploadFinished && <Card fileName={name}/>}
    </div>
  )
}

export default App
