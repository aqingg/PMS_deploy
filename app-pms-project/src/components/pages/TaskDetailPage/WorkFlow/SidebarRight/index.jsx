import React, { useState, useContext } from "react";
import { Button, Tooltip } from "antd";
import {
  DesktopOutlined,
  // FolderOpenOutlined,
  // CopyOutlined,
  CloudOutlined,
  GlobalOutlined,
} from "@ant-design/icons";
import { AppContext } from "../../../../../context/AppContext";
import "./index.css";

const iconStyle = { fontSize: "26px", color: "#ffffffff" };
// const childIconStyle = { fontSize: "20px", color: "white" };

export default function SidebarRight({ itemLabel, taskId, projectName, user }) {
  const [hover, setHover] = useState(null);
  const { actions } = useContext(AppContext);

  // ⭐ 构建统一的 Action Payload
  const payload = {
    label: itemLabel,
    taskId,
    projectName,
    user,
  };

  return (
    <div
      className={`sidebar-inline ${hover ? "expanded" : ""}`}
      onMouseLeave={() => setHover(null)}
    >
      {/* ===========================
          主按钮：Local
      =========================== */}
      <div className="inline-item">
        <Tooltip title="Local Folder" placement="top">
          <Button
            icon={<DesktopOutlined style={iconStyle} />}
            type="text"
            size="small"
            onClick={() => actions.openLocal(payload)}
          />
        </Tooltip>
      </div>
      {/* ===========================
          主按钮：Public
      =========================== */}
      <div className="inline-item">
        <Tooltip title="Public Folder" placement="top">
          <Button
            icon={<GlobalOutlined style={iconStyle} />}
            type="text"
            size="small"
            onClick={() => actions.openPublic(payload)}
          />
        </Tooltip>
      </div>

      {/* ===========================
          主按钮：SharePoint
      =========================== */}
      <div className="inline-item">
        <Tooltip title="SharePoint" placement="top">
          <Button
            icon={<CloudOutlined style={iconStyle} />}
            type="text"
            size="small"
            onClick={() => actions.openCloud(payload)}
          />
        </Tooltip>
      </div>
    </div>
  );
}
