import React from 'react';
import { Button, Tooltip } from 'antd';
import {
  ZoomInOutlined,
  EditOutlined,
  DeleteOutlined
} from '@ant-design/icons';
import './index.css';

const ProjectSidebar = ({ onAction, itemKey }) => {
  const iconStyle = { fontSize: '28px', color: 'white' };

  return (
    <div className="project-sidebar-slide-left">
      {/* 删除项目 */}
      <Tooltip title="Delete Project" placement="top">
        <Button
          icon={<DeleteOutlined style={iconStyle} />}
          size="small"
          type="text"
          onClick={() => onAction('deleteProject', itemKey)}
        />
      </Tooltip>
      {/* 编辑项目 */}
      <Tooltip title="Edit Project" placement="top">
        <Button
          icon={<EditOutlined style={iconStyle} />}
          size="small"
          type="text"
          onClick={() => onAction('editProject', itemKey)}
        />
      </Tooltip>
      {/* 打开项目 */}
      <Tooltip title="Open Project" placement="top">
        <Button
          icon={<ZoomInOutlined style={iconStyle} />}
          size="small"
          type="text"
          onClick={() => onAction('openProject', itemKey)}
        />
      </Tooltip>
    </div>
  );
};

export default ProjectSidebar;
