import React from 'react';
import { Progress } from 'antd';

export default function ProgressBar({ percent = 0, size = "default", showInfo = true }) {
  return (
    <div style={{ width: "100%" }}>
      <Progress 
        percent={percent} 
        size={size}
        showInfo={showInfo}
      />
    </div>
  );
}
