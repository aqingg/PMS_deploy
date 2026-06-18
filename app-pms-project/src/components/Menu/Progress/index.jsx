import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Typography, Tree, Space, message, Button, Modal, Input, Alert } from "antd";
import ProgressBar from "../ProgressBar";
import { useAppContext } from "../../../context/AppContext";

const { Title, Text } = Typography;

const clone = (obj) => JSON.parse(JSON.stringify(obj || {}));

const makeUuid = () => {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `id_${Date.now()}_${Math.random().toString(16).slice(2)}`;
};

const normalizeWorkflow = (workflow) => {
  if (!workflow) {
    return {
      taskTree: [],
      taskDetails: {},
    };
  }

  if (Array.isArray(workflow)) {
    return {
      taskTree: workflow,
      taskDetails: {},
    };
  }

  return {
    ...workflow,
    taskTree: Array.isArray(workflow.taskTree) ? workflow.taskTree : [],
    taskDetails:
      workflow.taskDetails && typeof workflow.taskDetails === "object"
        ? workflow.taskDetails
        : {},
  };
};

const getAllKeys = (nodes) => {
  const keys = [];

  const walk = (items) => {
    (items || []).forEach((item) => {
      if (item?.id) keys.push(item.id);
      if (item?.children?.length) walk(item.children);
    });
  };

  walk(nodes);
  return keys;
};

const findNodeById = (nodes, id) => {
  for (const node of nodes || []) {
    if (node.id === id) return node;
    if (node.children?.length) {
      const found = findNodeById(node.children, id);
      if (found) return found;
    }
  }
  return null;
};

const findNodeByTaskName = (nodes, taskName) => {
  const target = String(taskName || "").trim().toLowerCase();

  for (const node of nodes || []) {
    const current = String(node.taskName || "").trim().toLowerCase();
    if (current === target) return node;

    if (node.children?.length) {
      const found = findNodeByTaskName(node.children, taskName);
      if (found) return found;
    }
  }

  return null;
};

const findCalibrationRoot = (nodes) => {
  const exact = findNodeByTaskName(nodes, "C.Calibration");
  if (exact) return exact;

  const candidates = [];

  const walk = (items) => {
    (items || []).forEach((item) => {
      const name = String(item.taskName || "").trim().toLowerCase();
      if (name.includes("calibration")) {
        candidates.push(item);
      }
      if (item.children?.length) walk(item.children);
    });
  };

  walk(nodes);
  return candidates[0] || null;
};

const isDirectChild = (parent, childId) => {
  if (!parent?.children?.length || !childId) return false;
  return parent.children.some((child) => child.id === childId);
};

const removeNodeById = (nodes, id, removedIds = []) => {
  return (nodes || [])
    .filter((node) => {
      if (node.id === id) {
        const collect = (item) => {
          if (item?.id) removedIds.push(item.id);
          (item.children || []).forEach(collect);
        };
        collect(node);
        return false;
      }
      return true;
    })
    .map((node) => ({
      ...node,
      children: removeNodeById(node.children || [], id, removedIds),
    }));
};

const makeFallbackCalibrationTemplate = () => ({
  id: "template_root",
  taskName: "CalibrationID_Template",
  status: "Pending",
  children: [
    {
      id: "template_01_mds",
      taskName: "01_MDS",
      status: "Pending",
      children: [],
    },
    {
      id: "template_02_plan",
      taskName: "02_Calibration_Plan",
      status: "Pending",
      children: [],
    },
    {
      id: "template_03_results",
      taskName: "03_Results",
      status: "Pending",
      children: [
        {
          id: "template_email",
          taskName: "Customer Approval Email",
          status: "Pending",
          children: [],
        },
      ],
    },
    {
      id: "template_04_testing",
      taskName: "04_Testing",
      status: "Pending",
      children: [],
    },
    {
      id: "template_05_review",
      taskName: "05_Review",
      status: "Pending",
      children: [],
    },
    {
      id: "template_06_release",
      taskName: "06_Official_Release",
      status: "Pending",
      children: [
        {
          id: "template_tcd08",
          taskName: "ONETCD&TCD08_Report",
          status: "Pending",
          children: [],
        },
      ],
    },
  ],
});

const cloneCalibrationSubtree = (templateNode, newCalibrationId) => {
  const oldToNew = {};

  const cloneNode = (node, isRoot = false) => {
    const newId = makeUuid();
    oldToNew[node.id] = newId;

    return {
      ...node,
      id: newId,
      taskName: isRoot ? newCalibrationId : node.taskName,
      status: "Pending",
      children: (node.children || []).map((child) => cloneNode(child, false)),
    };
  };

  const newNode = cloneNode(templateNode, true);
  return { newNode, oldToNew };
};

const fillTaskDetailsFromTree = (workflow, newNode) => {
  if (!workflow.taskDetails || typeof workflow.taskDetails !== "object") {
    workflow.taskDetails = {};
  }

  const walk = (node) => {
    if (node?.id) {
      workflow.taskDetails[node.id] = {
        taskName: node.taskName || "Unnamed Task",
        status: node.status || "Pending",
      };
    }
    (node.children || []).forEach(walk);
  };

  walk(newNode);
};

export default function Progress() {
  const {
    projectWorkFlow,
    updateWorkFlow,
    user,
    projectName,
    projectId,
    createCalibrationWorkspace,
    createLocalFolders,
  } =
    useAppContext();

  const [localWorkflow, setLocalWorkflow] = useState(() =>
    normalizeWorkflow(projectWorkFlow)
  );
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [expandedKeys, setExpandedKeys] = useState([]);
  const [saving, setSaving] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [modalCalibrationId, setModalCalibrationId] = useState("");
  const [status, setStatus] = useState({
    type: "info",
    text: "点击“新增 CalibrationID”，输入名称后会复制已有 CalibrationID 的完整子树结构。",
  });

  useEffect(() => {
    const nextWorkflow = normalizeWorkflow(projectWorkFlow);
    setLocalWorkflow(nextWorkflow);
    setExpandedKeys(getAllKeys(nextWorkflow.taskTree));
  }, [projectWorkFlow]);

  const taskTree = localWorkflow?.taskTree || [];

  const countTasks = useCallback((node) => {
    let total = 1;
    let done = node.status === "Done" ? 1 : 0;
    let decline = node.status === "Decline" ? 1 : 0;

    (node.children || []).forEach((child) => {
      const result = countTasks(child);
      total += result.total;
      done += result.done;
      decline += result.decline;
    });

    return { total, done, decline };
  }, []);

  const overallProgress = useMemo(() => {
    if (!taskTree.length) return 0;

    let total = 0;
    let done = 0;
    let decline = 0;

    taskTree.forEach((node) => {
      const result = countTasks(node);
      total += result.total;
      done += result.done;
      decline += result.decline;
    });

    if (!total) return 0;
    return Math.round(((done + decline) / total) * 100);
  }, [taskTree, countTasks]);

  const treeData = useMemo(() => {
    const convert = (nodes) =>
      (nodes || []).map((item) => ({
        key: item.id,
        title: item.taskName || "Unnamed Task",
        children: item.children?.length ? convert(item.children) : [],
      }));

    return convert(taskTree);
  }, [taskTree]);

  const saveWorkflow = async (workflowToSave) => {
    if (!updateWorkFlow) {
      return { success: false, message: "updateWorkFlow 不存在" };
    }

    if (!projectId) {
      return { success: false, message: "projectId 缺失" };
    }

    if (!user?.username || user.username === "Unknown") {
      return { success: false, message: "username 缺失" };
    }

    try {
      const result = await updateWorkFlow({
        username: user.username,
        department: user.department,
        projectId,
        projectName,
        workflow: workflowToSave,
      });

      if (result?.success) {
        return { success: true };
      }

      return {
        success: false,
        message: result?.message || "后端保存 workflow 失败",
      };
    } catch (error) {
      return {
        success: false,
        message: error?.message || "保存 workflow 时发生异常",
      };
    }
  };

  const openAddModal = () => {
    setModalCalibrationId("");
    setAddModalOpen(true);
    setStatus({
      type: "info",
      text: "请输入新的 CalibrationID。新增时会复制 C.Calibration 下已有的完整子树结构。",
    });
  };

  const addCalibrationIdByModal = async () => {
    const cid = String(modalCalibrationId || "").trim();

    if (!cid) {
      setStatus({ type: "error", text: "新增失败：CalibrationID 不能为空。" });
      message.error("CalibrationID 不能为空");
      return;
    }

    const invalidPathChars = /[<>:"/\\|?*]/;
    if (invalidPathChars.test(cid)) {
      setStatus({
        type: "error",
        text: '新增失败：CalibrationID 不能包含非法字符 < > : " / \\ | ? *。',
      });
      message.error("CalibrationID 包含非法字符");
      return;
    }

    if (cid.includes("..")) {
      setStatus({ type: "error", text: "新增失败：CalibrationID 不能包含 '..'。" });
      message.error("CalibrationID 不能包含 '..'");
      return;
    }

    const updated = clone(normalizeWorkflow(localWorkflow));
    if (!Array.isArray(updated.taskTree)) {
      updated.taskTree = [];
    }

    let calibrationRoot = findCalibrationRoot(updated.taskTree);
    let createdRoot = false;

    if (!calibrationRoot) {
      calibrationRoot = {
        id: makeUuid(),
        taskName: "C.Calibration",
        status: "Pending",
        children: [],
      };
      updated.taskTree.push(calibrationRoot);
      createdRoot = true;
    }

    if (!Array.isArray(calibrationRoot.children)) {
      calibrationRoot.children = [];
    }

    const exists = calibrationRoot.children.some(
      (child) =>
        String(child.taskName || "").trim().toLowerCase() === cid.toLowerCase()
    );

    if (exists) {
      setExpandedKeys(getAllKeys(updated.taskTree));
      setStatus({ type: "warning", text: `新增失败：CalibrationID 已存在：${cid}` });
      message.warning(`CalibrationID 已存在：${cid}`);
      return;
    }

    let templateNode = null;
    let templateSource = "fallback";

    if (isDirectChild(calibrationRoot, selectedTaskId)) {
      templateNode = findNodeById(calibrationRoot.children, selectedTaskId);
      templateSource = `选中节点 ${templateNode?.taskName || ""}`;
    }

    if (!templateNode && calibrationRoot.children.length > 0) {
      templateNode = calibrationRoot.children[0];
      templateSource = `已有节点 ${templateNode.taskName}`;
    }

    if (!templateNode) {
      templateNode = makeFallbackCalibrationTemplate();
      templateSource = "默认模板";
    }

    const { newNode } = cloneCalibrationSubtree(templateNode, cid);
    calibrationRoot.children.push(newNode);

    if (createdRoot) {
      if (!updated.taskDetails || typeof updated.taskDetails !== "object") {
        updated.taskDetails = {};
      }
      updated.taskDetails[calibrationRoot.id] = {
        taskName: "C.Calibration",
        status: "Pending",
      };
    }

    fillTaskDetailsFromTree(updated, newNode);

    // 关键：先更新本地树，保证点击确定后马上能看到子树变化。
    setLocalWorkflow(updated);
    setExpandedKeys(getAllKeys(updated.taskTree));
    setSelectedTaskId(newNode.id);
    setAddModalOpen(false);
    setModalCalibrationId("");
    setStatus({
      type: "success",
      text: `页面已新增 ${cid}。模板来源：${templateSource}。正在保存到后端 workflow...`,
    });
    message.success(`页面已新增 CalibrationID：${cid}`);

    setSaving(true);
    const saveResult = await saveWorkflow(updated);

    if (saveResult.success) {
      setStatus({
        type: "info",
        text: `已新增 ${cid} 并保存 workflow。正在计算本地目录路径...`,
      });
      message.success(`workflow 保存成功：${cid}`);

      if (!createCalibrationWorkspace) {
        setStatus({
          type: "warning",
          text: `已新增 ${cid} 并保存 workflow，但 createCalibrationWorkspace 方法不存在，未计算本地目录路径。`,
        });
        message.warning("createCalibrationWorkspace 方法不存在");
        setSaving(false);
        return;
      }

      const workspaceResult = await createCalibrationWorkspace(cid);

      if (!workspaceResult?.success) {
        setStatus({
          type: "warning",
          text: `已新增 ${cid}，workflow 保存成功，但 8086 路径计算失败：${
            workspaceResult?.message || "未知错误"
          }`,
        });
        message.warning(`路径计算失败：${workspaceResult?.message || "未知错误"}`);
        setSaving(false);
        return;
      }

      const paths = workspaceResult?.paths || workspaceResult?.data?.paths || {};
      const folders = [
        paths.calibration_root,
        paths.email_dir,
        paths.tcd08_report_dir,
      ].filter(Boolean);

      if (!createLocalFolders) {
        setStatus({
          type: "warning",
          text: `已新增 ${cid}，workflow 保存成功，8086 已返回路径，但本地 createLocalFolders 方法不存在，未在用户电脑创建目录。`,
        });
        message.warning("createLocalFolders 方法不存在");
        setSaving(false);
        return;
      }

      setStatus({
        type: "info",
        text: `已新增 ${cid}，8086 路径计算成功。正在通过 7175 本地客户端创建目录...`,
      });

      const localFolderResult = await createLocalFolders(folders);
      setSaving(false);

      if (localFolderResult?.success) {
        setStatus({
          type: createdRoot ? "warning" : "success",
          text: createdRoot
            ? `已新增 ${cid}，workflow 保存成功，7175 已在用户电脑创建本地目录。注意：原 workflow 未找到 C.Calibration，本页面已自动创建该根节点。`
            : `已新增 ${cid}，workflow 保存成功，7175 已在用户电脑创建本地目录。`,
        });
        message.success(`本地目录创建成功：${cid}`);
      } else {
        setStatus({
          type: "warning",
          text: `已新增 ${cid}，workflow 保存成功，8086 已返回路径，但 7175 创建目录失败：${
            localFolderResult?.message || "未知错误"
          }`,
        });
        message.warning(`本地目录创建失败：${localFolderResult?.message || "未知错误"}`);
      }
    } else {
      setSaving(false);
      setStatus({
        type: "error",
        text: `页面已经显示 ${cid}，但后端保存失败：${saveResult.message}`,
      });
      message.error(`后端保存失败：${saveResult.message}`);
    }
  };

  const deleteSelectedTask = async () => {
    if (!selectedTaskId) {
      setStatus({ type: "error", text: "删除失败：请先选中一个节点。" });
      message.warning("请先选中一个节点");
      return;
    }

    const target = findNodeById(taskTree, selectedTaskId);
    if (!target) {
      setStatus({ type: "error", text: "删除失败：选中的节点不存在。" });
      message.error("选中的节点不存在");
      return;
    }

    const confirmed = window.confirm(`确定删除节点及其子节点：${target.taskName}？`);
    if (!confirmed) return;

    const updated = clone(normalizeWorkflow(localWorkflow));
    const removedIds = [];
    updated.taskTree = removeNodeById(updated.taskTree, selectedTaskId, removedIds);

    if (updated.taskDetails && typeof updated.taskDetails === "object") {
      removedIds.forEach((id) => {
        delete updated.taskDetails[id];
      });
    }

    setLocalWorkflow(updated);
    setExpandedKeys(getAllKeys(updated.taskTree));
    setSelectedTaskId(null);
    setStatus({
      type: "success",
      text: `页面已删除节点：${target.taskName}。正在保存到后端 workflow...`,
    });

    setSaving(true);
    const saveResult = await saveWorkflow(updated);
    setSaving(false);

    if (saveResult.success) {
      setStatus({ type: "success", text: `已删除 ${target.taskName}，并保存成功。` });
      message.success("删除成功");
    } else {
      setStatus({
        type: "error",
        text: `页面已经删除 ${target.taskName}，但后端保存失败：${saveResult.message}`,
      });
      message.error(`后端保存失败：${saveResult.message}`);
    }
  };

  const onSelect = (keys, info) => {
    const id = keys?.[0] || info?.node?.key || null;
    setSelectedTaskId(id);
    if (id && projectId) {
      window.location.hash = `#/task/${projectId}/${id}`;
    }
  };

  return (
    <div
      style={{
        height: "100%",
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
        padding: 12,
        boxSizing: "border-box",
        overflow: "hidden",
      }}
    >
      <div style={{ flex: "0 0 auto", marginBottom: 10 }}>
        <Space direction="vertical" size={4} style={{ width: "100%" }}>
          <Title level={5} style={{ margin: 0 }}>
            Project Detail
          </Title>
          <Text type="secondary">Whole Project Progress</Text>
          <ProgressBar percent={overallProgress} />
        </Space>
      </div>

      <div
        style={{
          flex: "0 0 auto",
          border: "1px solid #e5e7eb",
          borderRadius: 6,
          padding: 8,
          marginBottom: 8,
          background: "#fafafa",
        }}
      >
        <Space size={8} wrap>
          <Button type="primary" size="small" onClick={openAddModal} disabled={saving}>
            新增 CalibrationID
          </Button>

          <Button
            danger
            size="small"
            onClick={deleteSelectedTask}
            disabled={!selectedTaskId || saving}
          >
            删除所选节点
          </Button>
        </Space>
      </div>

      <div style={{ flex: "0 0 auto", marginBottom: 8 }}>
        <Alert
          showIcon
          type={status.type}
          message={status.text}
          style={{ paddingTop: 6, paddingBottom: 6 }}
        />
      </div>

      <div
        style={{
          flex: "1 1 auto",
          minHeight: 0,
          overflow: "auto",
          border: "1px solid #f0f0f0",
          borderRadius: 6,
          padding: 8,
          paddingRight: 14,
          background: "#fff",
        }}
      >
        {treeData.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="当前 workflow 树为空。请确认项目已经加载 workflow。"
          />
        ) : (
          <Tree
            blockNode
            treeData={treeData}
            expandedKeys={expandedKeys}
            selectedKeys={selectedTaskId ? [selectedTaskId] : []}
            onExpand={(keys) => setExpandedKeys(keys)}
            onSelect={onSelect}
          />
        )}
      </div>

      <Modal
        title="新增 CalibrationID"
        open={addModalOpen}
        onOk={addCalibrationIdByModal}
        onCancel={() => {
          if (!saving) {
            setAddModalOpen(false);
            setModalCalibrationId("");
          }
        }}
        okText="确定新增"
        cancelText="取消"
        confirmLoading={saving}
        maskClosable={!saving}
        destroyOnClose
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text>请输入新的 CalibrationID：</Text>
          <Input
            autoFocus
            value={modalCalibrationId}
            onChange={(event) => setModalCalibrationId(event.target.value)}
            onPressEnter={addCalibrationIdByModal}
            placeholder="例如 ACQ_AAAA-BBBB-CC"
            disabled={saving}
            allowClear
          />
          <Text type="secondary">
            新增时会复制 C.Calibration 下已有 CalibrationID 的完整子树；如果当前选中了
            C.Calibration 下的某个 CalibrationID，则优先复制该选中节点。
          </Text>
        </Space>
      </Modal>
    </div>
  );
}
