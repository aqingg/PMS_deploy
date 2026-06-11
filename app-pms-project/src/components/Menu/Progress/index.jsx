import React, { useMemo, useState, useEffect, useCallback  } from 'react';
import { Typography, Tree, Space, message, Tooltip } from 'antd';
import {
  CheckCircleOutlined,
  PauseCircleOutlined,
  MinusCircleOutlined,
  SyncOutlined,
  ProjectOutlined,
  CopyOutlined,
  DeleteOutlined
} from '@ant-design/icons';

import ProgressBar from '../ProgressBar';
import { useAppContext } from "../../../context/AppContext";

const { Title, Text } = Typography;

export default function Progress() {
  const { projectWorkFlow, updateWorkFlow, user, projectName, projectId } =
    useAppContext();

  const [selectedTaskId, setSelectedTaskId] = useState(null);

  const taskTree = useMemo(() => projectWorkFlow?.taskTree || [], [projectWorkFlow?.taskTree]);

  // ===========================
  // 状态图标
  // ===========================
  const getStatusIcon = (status) => {
    switch (status) {
      case "Done":
        return <CheckCircleOutlined style={{ color: "#52c41a", fontSize: 16 }} />;
      case "Pending":
        return <PauseCircleOutlined style={{ color: "#b9900a", fontSize: 16 }} />;
      case "Decline":
        return <MinusCircleOutlined style={{ color: "#707070", fontSize: 16 }} />;
      case "Ongoing":
        return <SyncOutlined spin style={{ color: "#1677ff", fontSize: 16 }} />;
      default:
        return null;
    }
  };

  // ===========================
  // DFS 统计节点
  // ===========================
  const countTasks = useCallback((node) => {
    let total = 1;
    let done = node.status === "Done" ? 1 : 0;
    let decline = node.status === "Decline" ? 1 : 0;

    if (node.children) {
      node.children.forEach((ch) => {
        const r = countTasks(ch);
        total += r.total;
        done += r.done;
        decline += r.decline;
      });
    }
    return { total, done, decline };
  }, []); 

  // ===========================
  // 整体进度
  // ===========================
  const overallProgress = useMemo(() => {
    if (!taskTree.length) return 0;

    let total = 0,
      done = 0,
      decline = 0;

    taskTree.forEach((node) => {
      const r = countTasks(node);
      total += r.total;
      done += r.done;
      decline += r.decline;
    });

    return Math.round(((done + decline) / total) * 100);
  }, [taskTree, countTasks]);

  // ===========================
  // 找到节点
  // ===========================
  const findNode = (nodes, id) => {
    for (const node of nodes) {
      if (node.id === id) return node;
      if (node.children?.length) {
        const res = findNode(node.children, id);
        if (res) return res;
      }
    }
    return null;
  };

  // ===========================
  // 找到父节点
  // ===========================
  /*const findParent = (nodes, id, parent = null) => {
    for (const node of nodes) {
      if (node.id === id) return parent;
      if (node.children?.length) {
        const res = findParent(node.children, id, node);
        if (res) return res;
      }
    }
    return null;
  };*/

  // ===========================
  // 深度复制：全新 UUID
  // ===========================
  const uuid = () => crypto.randomUUID();

  const deepCopyTask = (task, newDetails) => {
    const newId = uuid();

    if (projectWorkFlow.taskDetails[task.id]) {
      newDetails[newId] = {
        ...projectWorkFlow.taskDetails[task.id],
        taskName: projectWorkFlow.taskDetails[task.id].taskName + " (Copy)"
      };
    }

    return {
      ...task,
      id: newId,
      status: "Pending",
      children: task.children?.map((ch) => deepCopyTask(ch, newDetails)) || [],
    };
  };

  const findParentAndIndex = (nodes, id, parent = null) => {
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];

      if (node.id === id) {
        return { parent, index: i, siblings: nodes };
      }

      if (node.children?.length) {
        const res = findParentAndIndex(node.children, id, node);
        if (res) return res;
      }
    }
    return null;
  };

  // ===========================
  // 复制 Task
  // ===========================
  const copySelectedTask = async () => {
    if (!selectedTaskId) {
      message.warning("Please select a task from the tree first");
      return;
    }

    const updated = JSON.parse(JSON.stringify(projectWorkFlow));
    const node = findNode(updated.taskTree, selectedTaskId);
    if (!node) return;

    const pos = findParentAndIndex(updated.taskTree, selectedTaskId);

    const newDetails = {};
    const clone = deepCopyTask(node, newDetails);

    updated.taskDetails = { ...updated.taskDetails, ...newDetails };

    if (pos) {
      const { siblings, index } = pos;
      siblings.splice(index + 1, 0, clone);
    } 
    else {
      // 理论上不会发生，兜底
      updated.taskTree.push(clone);
    }

    await updateWorkFlow({
      username: user.username,
      department: user.department,
      projectId: projectId,
      projectName,
      workflow: updated,
    });

    message.success("Task copied!");
  };

  // ===========================
  // 删除 Task
  // ===========================
  const deleteSelectedTask = async () => {
    if (!selectedTaskId) {
      message.warning("Please select a task from the tree first");
      return;
    }

    const updated = JSON.parse(JSON.stringify(projectWorkFlow));

    const removeNode = (nodes, id) => {
      return nodes.filter((node) => {
        if (node.id === id) return false;
        if (node.children) node.children = removeNode(node.children, id);
        return true;
      });
    };

    updated.taskTree = removeNode(updated.taskTree, selectedTaskId);

    await updateWorkFlow({
      username: user.username,
      department: user.department,
      projectId: projectId,
      projectName,
      workflow: updated,
    });

    message.success("Task deleted!");
  };

  // ===========================
  // TreeData
  // ===========================
  const treeData = useMemo(() => {
    const convert = (nodes) =>
      nodes.map((item) => ({
        key: item.id,
        icon: getStatusIcon(item.status),
        title: item.taskName,
        children: item.children ? convert(item.children) : [],
      }));

    return convert(taskTree);
  }, [taskTree]);

  const getAllKeys = (nodes) => {
    const keys = [];
    const dfs = (items) => {
      items.forEach((item) => {
        keys.push(item.id);
        if (item.children?.length) dfs(item.children);
      });
    };
    dfs(nodes);
    return keys;
  };

  // ===========================
  // ⭐ 初次加载自动展开全部
  // ===========================
  const [expandedKeys, setExpandedKeys] = useState([]);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (!initialized && taskTree.length > 0) {
      setExpandedKeys(getAllKeys(taskTree));
      setInitialized(true);
    }
  }, [taskTree, initialized]);

  const onExpand = (keys) => {
    setExpandedKeys(keys); // 用户折叠/展开后更新
  };

  // ===========================
  // UI
  // ===========================
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, height: "100%" }}>

      {/* 顶部标题 + 按钮 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Title level={4} style={{ margin: 0 }}>Project Detail</Title>

        <div style={{ display: "flex", gap: 10 }}>
          <Tooltip title="Copy Selected Task">
            <CopyOutlined style={{ fontSize: 15, cursor: "pointer" }} onClick={copySelectedTask} />
          </Tooltip>

          <Tooltip title="Delete Selected Task">
            <DeleteOutlined style={{ fontSize: 15, color: "#ff0101", cursor: "pointer" }} onClick={deleteSelectedTask} />
          </Tooltip>
        </div>
      </div>

      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        <Text type="secondary" style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
          <ProjectOutlined /> Whole Project Progress
        </Text>
        <ProgressBar percent={overallProgress} />
      </Space>

      <div style={{ overflow: "auto", flex: 1 }}>
        <Tree
          showIcon
          expandedKeys={expandedKeys}
          onExpand={onExpand}
          treeData={treeData}
          onSelect={(keys, info) => {
            const uuid = info.node.key;
            setSelectedTaskId(uuid);
            window.location.hash = `#/task/${projectId}/${uuid}`;
          }}
        />
      </div>
    </div>
  );
}
