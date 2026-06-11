import React from "react";
import { Button, Tooltip } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  LinkOutlined
} from "@ant-design/icons";

import "./index.css";

const Sidebar = ({ onAction, todoId, hasLink, canEdit, canDelete }) => {
  const iconStyle = { fontSize: "30px", color: "white" };

  return (
    <div className="sidebar-slide-left">
      {hasLink && (
        <Tooltip title="Open Link">
          <Button
            icon={<LinkOutlined style={iconStyle} />}
            type="text"
            onClick={() => onAction("open_link", todoId)}
          />
        </Tooltip>
      )}

      {canDelete && (
        <Tooltip title="Delete">
          <Button
            icon={<DeleteOutlined style={iconStyle} />}
            type="text"
            onClick={() => onAction("delete", todoId)}
          />
        </Tooltip>
      )}

      {canEdit && (
        <Tooltip title="Edit">
          <Button
            icon={<EditOutlined style={iconStyle} />}
            type="text"
            onClick={() => onAction("edit", todoId)}
          />
        </Tooltip>
      )}

      <Tooltip title="Pending">
        <Button
          icon={<CloseCircleOutlined style={iconStyle} />}
          type="text"
          onClick={() => onAction("pending", todoId)}
        />
      </Tooltip>

      <Tooltip title="Ongoing">
        <Button
          icon={<ClockCircleOutlined style={iconStyle} />}
          type="text"
          onClick={() => onAction("ongoing", todoId)}
        />
      </Tooltip>

      <Tooltip title="Done">
        <Button
          icon={<CheckCircleOutlined style={iconStyle} />}
          type="text"
          onClick={() => onAction("done", todoId)}
        />
      </Tooltip>
    </div>
  );
};


export default Sidebar;
