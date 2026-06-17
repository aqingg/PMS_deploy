import React from 'react';
import { Card } from 'antd';
import ProjectInfo from './ProjectInfo';
import Progress from './Progress';
import './index.css';

export default function Menu({
  user,
  projectName,
  projectInfo,
  projectWorkFlow,
  projectProgress
}) {

  return (
    <div className="menu-wrapper">

      {/* 项目信息 Card */}
      <div className="menu-project-info">
        <Card
          size="small"
          bordered={false}
          style={{ height: "100%", boxShadow: "0 1px 2px rgba(0,0,0,0.08)" }}
        >
          <ProjectInfo/>
        </Card>
      </div>

      {/* 项目流程 Card */}
      <div className="menu-progress">
        <Card
            size="small"
            bordered={false}
            style={{ 
              height: "100%", 
              boxShadow: "0 1px 2px rgba(0,0,0,0.08)" 
            }}
            bodyStyle={{
              height: "100%",          // ⭐ 让 card-body 占满高度
              padding: 12,
              display: "flex",         // ⭐ 让内容区成为 flex 容器
              flexDirection: "column",
              minHeight: 0,            // ⭐ ⭐ 必须：允许子容器收缩
              boxSizing: "border-box",
            }}
          >
          <Progress/>
        </Card>
      </div>
    </div>
  );
}
