import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Typography,
  Tree,
  Space,
  message,
  Button,
  Modal,
  Input,
  Alert,
  Tooltip,
} from "antd";
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

const normalizeStatus = (status) => {
  const value = String(status || "Pending").trim().toLowerCase();
  if (value === "ongoing" || value === "in progress" || value === "in_progress") {
    return "Ongoing";
  }
  if (value === "done" || value === "success" || value === "finished") {
    return "Done";
  }
  if (value === "decline" || value === "declined" || value === "rejected") {
    return "Decline";
  }
  return "Pending";
};

const renderStatusIcon = (status) => {
  const normalized = normalizeStatus(status);
  const iconStyle = {
    fontSize: 15,
    flex: "0 0 auto",
    lineHeight: 1,
  };

  switch (normalized) {
    case "Ongoing":
      return (
        <Tooltip title="Ongoing">
          <SyncOutlined spin style={{ ...iconStyle, color: "#1677ff" }} />
        </Tooltip>
      );
    case "Done":
      return (
        <Tooltip title="Done">
          <CheckCircleOutlined style={{ ...iconStyle, color: "#52c41a" }} />
        </Tooltip>
      );
    case "Decline":
      return (
        <Tooltip title="Decline">
          <MinusCircleOutlined style={{ ...iconStyle, color: "#707070" }} />
        </Tooltip>
      );
    case "Pending":
    default:
      return (
        <Tooltip title="Pending">
          <PauseCircleOutlined style={{ ...iconStyle, color: "#b9900a" }} />
        </Tooltip>
      );
  }
};

const renderTreeTitle = (item) => {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        minWidth: 0,
      }}
    >
      {renderStatusIcon(item.status)}
      <span>{item.taskName || "Unnamed Task"}</span>
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
  } = useAppContext();

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
    text: "Here is workflow",
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
        title: renderTreeTitle(item),
        children: item.children?.length ? convert(item.children) : [],
      }));

    return convert(taskTree);
  }, [taskTree]);

  const saveWorkflow = async (workflowToSave) => {
    if (!updateWorkFlow) {
      return { success: false, message: "updateWorkFlow does not exist" };
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
        message: result?.message || "Backend workflow save failed",
      };
    } catch (error) {
      return {
        success: false,
        message: error?.message || "An exception occurred while saving workflow",
      };
    }
  };

  const openAddModal = () => {
    setModalCalibrationId("");
    setAddModalOpen(true);
    setStatus({
      type: "info",
      text: "Enter a new CalibrationID.\nThe full subtree under C.Calibration will be copied.",
    });
  };

  const addCalibrationIdByModal = async () => {
    const cid = String(modalCalibrationId || "").trim();

    if (!cid) {
      setStatus({ type: "error", text: "Add failed: CalibrationID is required." });
      message.error("CalibrationID is required");
      return;
    }

    const invalidPathChars = /[<>:"/\\|?*]/;
    if (invalidPathChars.test(cid)) {
      setStatus({
        type: "error",
        text: "Add failed: CalibrationID contains invalid characters.",
      });
      message.error("Invalid characters in CalibrationID");
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
      (child) => String(child.taskName || "").trim().toLowerCase() === cid.toLowerCase()
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

    setLocalWorkflow(updated);
    setExpandedKeys(getAllKeys(updated.taskTree));
    setSelectedTaskId(newNode.id);
    setAddModalOpen(false);
    setModalCalibrationId("");
    setStatus({
      type: "success",
      text: `Added ${cid} on page. Template source: ${templateSource}. Saving workflow...`,
    });
    message.success(`CalibrationID added on page: ${cid}`);

    setSaving(true);
    const saveResult = await saveWorkflow(updated);

    if (saveResult.success) {
      setStatus({
        type: "info",
        text: `${cid} added and workflow saved.\nCalculating local directory path...`,
      });
      message.success(`Workflow saved: ${cid}`);

      if (!createCalibrationWorkspace) {
        setStatus({
          type: "warning",
          text: `${cid} added and workflow saved, but createCalibrationWorkspace is unavailable.\nNo path calculated.`,
        });
        message.warning("createCalibrationWorkspace method is unavailable");
        setSaving(false);
        return;
      }

      const workspaceResult = await createCalibrationWorkspace(cid);
      if (!workspaceResult?.success) {
        setStatus({
          type: "warning",
          text: `${cid} added and workflow saved, but 8086 path calculation failed: ${
            workspaceResult?.message || "Unknown error"
          }`,
        });
        message.warning(`Path calculation failed: ${workspaceResult?.message || "Unknown error"}`);
        setSaving(false);
        return;
      }

      const paths = workspaceResult?.paths || workspaceResult?.data?.paths || {};
      const folders = (
        Array.isArray(paths.folders)
          ? paths.folders
          : [paths.calibration_root, paths.email_dir, paths.tcd08_report_dir]
      ).filter(Boolean);

      if (!createLocalFolders) {
        setStatus({
          type: "warning",
          text: `${cid} added and workflow saved, path returned, but createLocalFolders is unavailable.\nNo local directory created.`,
        });
        message.warning("createLocalFolders method is unavailable");
        setSaving(false);
        return;
      }

      setStatus({
        type: "info",
        text: `${cid} path calculated. Creating directories via 7175 local client...`,
      });

      const localFolderResult = await createLocalFolders(folders);
      setSaving(false);

      if (localFolderResult?.success) {
        setStatus({
          type: createdRoot ? "warning" : "success",
          text: createdRoot
            ? `${cid} added and workflow saved. Local directories created by 7175.\nNote: C.Calibration root was auto-created because it was missing.`
            : `${cid} added and workflow saved.\nLocal directories created by 7175.`,
        });
        message.success(`Local directories created: ${cid}`);
      } else {
        setStatus({
          type: "warning",
          text: `${cid} added and workflow saved, 8086 path returned, but 7175 directory creation failed: ${
            localFolderResult?.message || "Unknown error"
          }`,
        });
        message.warning(`Failed to create local directories: ${localFolderResult?.message || "Unknown error"}`);
      }
    } else {
      setSaving(false);
      setStatus({
        type: "error",
        text: `${cid} is shown on page, but backend save failed: ${saveResult.message}`,
      });
      message.error(`Backend save failed: ${saveResult.message}`);
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
      setStatus({ type: "error", text: "Delete failed: selected node does not exist." });
      message.error("Selected node does not exist");
      return;
    }

    const confirmed = window.confirm(`Delete node and its children: ${target.taskName}?`);
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
      text: `Node deleted on page: ${target.taskName}.\nSaving to backend workflow...`,
    });

    setSaving(true);
    const saveResult = await saveWorkflow(updated);
    setSaving(false);

    if (saveResult.success) {
      setStatus({ type: "success", text: `${target.taskName} deleted and saved.` });
      message.success("Deleted successfully");
    } else {
      setStatus({
        type: "error",
        text: `${target.taskName} removed on page, but backend save failed: ${saveResult.message}`,
      });
      message.error(`Backend save failed: ${saveResult.message}`);
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
        padding: "0 12px",
        height: "100%",
        maxHeight: "100%",
        overflow: "auto",
        boxSizing: "border-box",
      }}
    >
      <Title level={5} style={{ marginTop: 8 }}>
        Project Detail
      </Title>

      <Text type="secondary">Whole Project Progress</Text>
      <ProgressBar percent={overallProgress} />

      <Space style={{ marginTop: 12, marginBottom: 12 }}>
        <Button type="primary" size="small" onClick={openAddModal} disabled={saving}>
          Add CalibrationID
        </Button>
        <Button danger size="small" onClick={deleteSelectedTask} disabled={saving}>
          Delete Selected Node
        </Button>
      </Space>

      <Alert
        type={status.type || "info"}
        message={status.text || "Here is workflow"}
        showIcon
        style={{ marginBottom: 12, whiteSpace: "pre-line" }}
      />

      {treeData.length === 0 ? (
        <Text type="secondary">No workflow data.</Text>
      ) : (
        <Tree
          treeData={treeData}
          expandedKeys={expandedKeys}
          selectedKeys={selectedTaskId ? [selectedTaskId] : []}
          onExpand={(keys) => setExpandedKeys(keys)}
          onSelect={onSelect}
        />
      )}

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
        <Text>Enter new CalibrationID:</Text>
        <Input
          style={{ marginTop: 8 }}
          value={modalCalibrationId}
          onChange={(event) => setModalCalibrationId(event.target.value)}
          onPressEnter={addCalibrationIdByModal}
          placeholder="e.g. ACQ_AAAA-BBBB-CC"
          disabled={saving}
          allowClear
        />
        <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
          A new node will copy the full subtree of an existing CalibrationID under C.Calibration.
        </Text>
      </Modal>
    </div>
  );
}
