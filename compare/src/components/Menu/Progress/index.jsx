import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Typography, Tree, Space, message, Button, Modal, Input, Alert } from "antd";
import {
  PauseCircleOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  MinusCircleOutlined,
} from "@ant-design/icons";
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

const normalizeStatusForIcon = (status) => {
  const value = String(status || "Pending").trim().toLowerCase();

  if (["ongoing", "on going", "in progress", "in_progress"].includes(value)) {
    return "Ongoing";
  }

  if (["done", "finished", "finish", "success", "completed", "complete"].includes(value)) {
    return "Done";
  }

  if (["decline", "declined", "reject", "rejected"].includes(value)) {
    return "Decline";
  }

  return "Pending";
};

const renderStatusIcon = (status) => {
  const iconStyle = {
    marginRight: 6,
    verticalAlign: "-0.125em",
  };

  switch (normalizeStatusForIcon(status)) {
    case "Ongoing":
      return <SyncOutlined spin style={{ ...iconStyle, color: "#1677ff" }} />;
    case "Done":
      return <CheckCircleOutlined style={{ ...iconStyle, color: "#52c41a" }} />;
    case "Decline":
      return <MinusCircleOutlined style={{ ...iconStyle, color: "#8c8c8c" }} />;
    case "Pending":
    default:
      return <PauseCircleOutlined style={{ ...iconStyle, color: "#d48806" }} />;
  }
};

const renderTreeTitle = (item) => {
  const title = item?.taskName || "Unnamed Task";

  return (
    <span title={title}>
      {renderStatusIcon(item?.status)}
      {title}
    </span>
  );
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
    text: "Click 'Add CalibrationID', enter a name, and the complete subtree of an existing CalibrationID will be copied."  });

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
        title: renderTreeTitle(item),
        children: item.children?.length ? convert(item.children) : [],
      }));

    return convert(taskTree);
  }, [taskTree]);

  const saveWorkflow = async (workflowToSave) => {
    if (!updateWorkFlow) {
      return { success: false, message: "updateWorkFlow is unavailable" };
    }

    if (!projectId) {
      return { success: false, message: "projectId is missing" };
    }

    if (!user?.username || user.username === "Unknown") {
      return { success: false, message: "username is missing" };
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
        message: result?.message || "Failed to save workflow on the server",
      };
    } catch (error) {
      return {
        success: false,
        message: error?.message || "An error occurred while saving workflow",
      };
    }
  };

  const openAddModal = () => {
    setModalCalibrationId("");
    setAddModalOpen(true);
    setStatus({
      type: "info",
      text: "Please enter a new CalibrationID. The complete subtree under an existing CalibrationID in C.Calibration will be copied.",
    });
  };

  const addCalibrationIdByModal = async () => {
    const cid = String(modalCalibrationId || "").trim();

    if (!cid) {
      setStatus({ type: "error", text: "Add failed: CalibrationID cannot be empty." });
      message.error("CalibrationID cannot be empty");
      return;
    }

    const invalidPathChars = /[<>:"/\\|?*]/;
    if (invalidPathChars.test(cid)) {
      setStatus({
        type: "error",
        text: 'Add failed: CalibrationID cannot contain invalid characters: < > : " / \\ | ? *.',
      });
      message.error("CalibrationID contains invalid characters");
      return;
    }

    if (cid.includes("..")) {
      setStatus({ type: "error", text: "Add failed: CalibrationID cannot contain '..'." });
      message.error("CalibrationID cannot contain '..'");
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
      setStatus({ type: "warning", text: `Add failed: CalibrationID already exists: ${cid}` });
      message.warning(`CalibrationID already exists: ${cid}`);
      return;
    }

    let templateNode = null;
    let templateSource = "fallback";

    if (isDirectChild(calibrationRoot, selectedTaskId)) {
      templateNode = findNodeById(calibrationRoot.children, selectedTaskId);
      templateSource = `selected node ${templateNode?.taskName || ""}`;
    }

    if (!templateNode && calibrationRoot.children.length > 0) {
      templateNode = calibrationRoot.children[0];
      templateSource = `existing node ${templateNode.taskName}`;
    }

    if (!templateNode) {
      templateNode = makeFallbackCalibrationTemplate();
      templateSource = "default template";
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
      text: `Added ${cid} on this page. Template source: ${templateSource}. Saving workflow to the server...`,
    });
    message.success(`CalibrationID added on this page: ${cid}`);

    setSaving(true);
    const saveResult = await saveWorkflow(updated);

    if (saveResult.success) {
      setStatus({
        type: "info",
        text: `Added ${cid} and saved workflow. Calculating local folder paths...`,
      });
      message.success(`Workflow saved successfully: ${cid}`);

      if (!createCalibrationWorkspace) {
        setStatus({
          type: "warning",
          text: `Added ${cid} and saved workflow, but createCalibrationWorkspace is unavailable. Local folder paths were not calculated.`,
        });
        message.warning("createCalibrationWorkspace is unavailable");
        setSaving(false);
        return;
      }

      const workspaceResult = await createCalibrationWorkspace(cid);

      if (!workspaceResult?.success) {
        setStatus({
          type: "warning",
          text: `Added ${cid} and saved workflow, but 8086 path calculation failed: ${
            workspaceResult?.message || "Unknown error"
          }`,
        });
        message.warning(`Path calculation failed: ${workspaceResult?.message || "Unknown error"}`);
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
          text: `Added ${cid}; workflow saved and 8086 returned paths, but createLocalFolders is unavailable. Local folders were not created on the user computer.`,
        });
        message.warning("createLocalFolders is unavailable");
        setSaving(false);
        return;
      }

      setStatus({
        type: "info",
        text: `Added ${cid}. 8086 path calculation succeeded. Creating folders through the 7175 local client...`,
      });

      const localFolderResult = await createLocalFolders(folders);
      setSaving(false);

      if (localFolderResult?.success) {
        setStatus({
          type: createdRoot ? "warning" : "success",
          text: createdRoot
            ? `Added ${cid}; workflow saved and local folders were created on the user computer through 7175. Note: C.Calibration was not found in the original workflow, so this root node was created automatically.`
            : `Added ${cid}; workflow saved and local folders were created on the user computer through 7175.`,
        });
        message.success(`Local folders created successfully: ${cid}`);
      } else {
        setStatus({
          type: "warning",
          text: `Added ${cid}; workflow saved and 8086 returned paths, but 7175 failed to create local folders: ${
            localFolderResult?.message || "Unknown error"
          }`,
        });
        message.warning(`Local folder creation failed: ${localFolderResult?.message || "Unknown error"}`);
      }
    } else {
      setSaving(false);
      setStatus({
        type: "error",
        text: `${cid} is displayed on this page, but server save failed: ${saveResult.message}`,
      });
      message.error(`Server save failed: ${saveResult.message}`);
    }
  };

  const deleteSelectedTask = async () => {
    if (!selectedTaskId) {
      setStatus({ type: "error", text: "Delete failed: please select a node first." });
      message.warning("Please select a node first");
      return;
    }

    const target = findNodeById(taskTree, selectedTaskId);
    if (!target) {
      setStatus({ type: "error", text: "Delete failed: the selected node does not exist." });
      message.error("The selected node does not exist");
      return;
    }

    const confirmed = window.confirm(`Delete this node and all child nodes: ${target.taskName}?`);
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
      text: `Deleted node on this page: ${target.taskName}. Saving workflow to the server...`,
    });

    setSaving(true);
    const saveResult = await saveWorkflow(updated);
    setSaving(false);

    if (saveResult.success) {
      setStatus({ type: "success", text: `Deleted ${target.taskName} and saved successfully.` });
      message.success("Deleted successfully");
    } else {
      setStatus({
        type: "error",
        text: `${target.taskName} has been deleted on this page, but server save failed: ${saveResult.message}`,
      });
      message.error(`Server save failed: ${saveResult.message}`);
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
            Add CalibrationID
          </Button>

          <Button
            danger
            size="small"
            onClick={deleteSelectedTask}
            disabled={!selectedTaskId || saving}
          >
            Delete Selected Node
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
            message="The current workflow tree is empty. Please confirm that the workflow has been loaded."
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
        title="Add CalibrationID"
        open={addModalOpen}
        onOk={addCalibrationIdByModal}
        onCancel={() => {
          if (!saving) {
            setAddModalOpen(false);
            setModalCalibrationId("");
          }
        }}
        okText="Add"
        cancelText="Cancel"
        confirmLoading={saving}
        maskClosable={!saving}
        destroyOnClose
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text>Please enter a new CalibrationID:</Text>
          <Input
            autoFocus
            value={modalCalibrationId}
            onChange={(event) => setModalCalibrationId(event.target.value)}
            onPressEnter={addCalibrationIdByModal}
            placeholder="Example: ACQ_AAAA-BBBB-CC"
            disabled={saving}
            allowClear
          />
          <Text type="secondary">
            When adding a new CalibrationID, the complete subtree of an existing CalibrationID under C.Calibration will be copied. 
          </Text>
        </Space>
      </Modal>
    </div>
  );
}
//显示工作树流程，提供新增树。