import React, { useState, useEffect, useCallback  } from "react";
import { useParams } from "react-router-dom";
import {
  Button,
  Divider,
  Row,
  Col,
  Card,
  message,
  Input,
  Tooltip,
  Modal,
  Form,
  Spin,
} from "antd";

import WorkFlow from "./WorkFlow";
import { useAppContext } from "../../../context/AppContext";

import {
  PauseCircleOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  MinusCircleOutlined,
  EditOutlined,
} from "@ant-design/icons";

export default function TaskDetailPage() {
  const [messageApi, contextHolder] = message.useMessage();
  const { projectId, taskId } = useParams();
  const { projectWorkFlow, projectName, projectInfo, getParameter, getRealPathFromBackend, getOfficeFiles, user, updateWorkFlow, getWorkFlowTemplate } =
  useAppContext();

  const [currentTask, setCurrentTask] = useState(null);

  // 来自 WorkFlow.json 的模板
  const [template, setTemplate] = useState(null);

  // UI — TaskDetail
  const [taskInputs, setTaskInputs] = useState([]);
  const [taskOutputs, setTaskOutputs] = useState([]);
  const [taskOperation, setTaskOperation] = useState(null);
  const [taskDescription, setTaskDescription] = useState("");

  const [taskNotFound, setTaskNotFound] = useState(false);

  // Modal
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [newTaskName, setNewTaskName] = useState("");

  // 操作执行中等待弹窗
  const [loadingModalOpen, setLoadingModalOpen] = useState(false);
  const [loadingText, setLoadingText] = useState("");

  // 允许中文，不允许真正危险字符
  const ILLEGAL_REGEX = /[/\\<>{}[\]"'`|]/g;

  // ================================
  // 工具函数：根据 UUID 找任务节点
  // ================================
  const findTaskNodeById = useCallback((nodes, id) => {
    for (const node of nodes) {
      if (node.id === id) return node;
      if (node.children?.length) {
        const res = findTaskNodeById(node.children, id);
        if (res) return res;
      }
    }
    return null;
  }, []);

  // ================================
  // 1) 加载当前任务
  // ================================
  useEffect(() => {
    if (!projectWorkFlow?.taskTree) return;

    const node = findTaskNodeById(projectWorkFlow.taskTree, taskId);
    setCurrentTask(node || null);
  }, [projectWorkFlow, taskId, findTaskNodeById]);

  // ================================
  // 2) 从 AppContext 加载 WorkFlow 模板
  // ================================
  useEffect(() => {
    const loadTemplate = async () => {
      const res = await getWorkFlowTemplate();
      if (res.success) {
        setTemplate(res.data);
      } else {
        console.error("Failed to load workflow template:", res.error);
      }
    };

    loadTemplate();
  }, [getWorkFlowTemplate]);

  // ================================
  // 3) 根据模板填充 inputs / outputs / operation
  // ================================
  useEffect(() => {
    if (!currentTask) return;
    if (!template) return;

    const detail = template[currentTask.taskName];

    if (!detail) {
      setTaskNotFound(true);
      setTaskDescription("No workflow template defined for this task.");
      return;
    }

    setTaskNotFound(false);
    setTaskInputs(detail.inputs || []);
    setTaskOutputs(detail.outputs || []);
    setTaskOperation(detail.operation || null);
    setTaskDescription(detail.description || "");
  }, [currentTask, template]);

  // ======================================================
  // 提前拦截 — 如果 currentTask 未加载，直接 Loading
  // ======================================================
  if (!currentTask) {
    return (
      <div>
        {contextHolder}
        <div style={{ padding: 20 }}>Loading Task...</div>
      </div>
    );
  }

  // ================================
  // 更新状态
  // ================================
  const updateStatus = async (newStatus) => {
    const updated = JSON.parse(JSON.stringify(projectWorkFlow));
    const task = findTaskNodeById(updated.taskTree, taskId);

    if (!task) return;

    task.status = newStatus;

    await updateWorkFlow({
      username: user.username,
      department: user.department,
      workflow: updated,
      projectId: Number(projectId),
    });
  };

  // ================================
  // 保存任务名
  // ================================
  const updateTaskName = async () => {
    const cleaned = newTaskName.replace(ILLEGAL_REGEX, "");

    if (!cleaned.trim()) {
      messageApi.error("Task name cannot be empty");
      return;
    }

    const updated = JSON.parse(JSON.stringify(projectWorkFlow));
    const node = findTaskNodeById(updated.taskTree, taskId);

    if (!node) return;

    node.taskName = cleaned; // 修改 taskTree 的名字

    const res = await updateWorkFlow({
      username: user.username,
      department: user.department,
      workflow: updated,
      projectId: Number(projectId),
    });

    if (res.success) {
      //messageApi.success("Task name updated!");
      setEditModalOpen(false);
    } else {
      messageApi.error("Update failed");
    }
  };

  // ================================
  // 定义 Operation 行为
  // ================================
  async function handleHttpWithParameter(operation_detail) {
    // 0. 获取需要注入的参数名列表
    const { need_parameter: parameterNames } = operation_detail;
    // 校验输入是否为数组
    if (!Array.isArray(parameterNames)) {
      throw new Error("配置错误：'need_parameter' 必须是一个数组。");
    }

    // 创建一个Promise数组，每个Promise负责获取一个参数
    const parameterPromises = parameterNames.map(name => getParameter(name));

    // 并行等待所有参数获取完成
    const parameterResults = await Promise.all(parameterPromises);
    const type = "local";
    const isTCD08Fill = operation_detail.url?.includes("/fillTCD08Report");

    let input_files = [];
    if (!isTCD08Fill) {
      const input_path = await getRealPathFromBackend({ label: taskInputs[0].label, taskId, projectId, user, type });
      input_files = await getOfficeFiles(input_path);
    }

    const output_path = await getRealPathFromBackend({ label: taskOutputs[0].label, taskId, projectId, user, type });

    // 1. 构建最终请求体
    let { url, method, body } = operation_detail;
    const finalBody = JSON.parse(JSON.stringify(body || {}));

    // 将获取到的所有参数写入 finalBody
    parameterNames.forEach((name, index) => {
      const parameterValue = parameterResults[index].parameter;
      finalBody[name] = parameterValue;
    });

    finalBody.template_paths = input_files;
    finalBody.save_path = output_path;
    if (isTCD08Fill) {
      finalBody.project_info = projectInfo;
      finalBody.projectId = Number(projectId);
      finalBody.taskId = taskId;
    }

    // 2. 发送请求
    const response = await fetch(url, {
      method: method,
      headers: {
        'Content-Type': 'application/json',
      },
      body: finalBody ? JSON.stringify(finalBody) : undefined,
    });

    // 3. 错误处理
    if (!response.ok) {
      let errorMessage = `请求失败: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData && errorData.message) {
          errorMessage = errorData.message;
        }
      } catch (e) {
        // 响应体不是JSON或为空
      }
      throw new Error(errorMessage);
    }
    
    // 4. 成功处理
    try {
      return await response.json();
    } catch (e) {
      return null; // 响应体为空或不是JSON
    }
  }

  // ================================
  // UI
  // ================================
  return (
    <div>
      {contextHolder}

      {/* Header */}
      <Row align="middle">
        <Col flex="auto">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 className="text-2xl font-bold m-0">{currentTask.taskName}</h1>

            <Tooltip title="Edit Task Name">
              <Button
                type="text"
                icon={<EditOutlined />}
                onClick={() => {
                  setNewTaskName(currentTask.taskName);
                  setEditModalOpen(true);
                }}
              />
            </Tooltip>
          </div>

          <p style={{ marginTop: 4, color: "#666", fontSize: 15 }}>
            {taskDescription}
          </p>
        </Col>
      </Row>
      <Divider />

      {/* ===== Main Content ===== */}
      <Card size="small" style={{ marginTop: 12, padding: 16 }}>
        {/* ⭐ 状态按钮永远显示 */}
        <div style={{ marginBottom: 16, display: "flex", gap: 18 }}>
          <Tooltip title="Pending">
            <PauseCircleOutlined
              style={{ fontSize: 28, color: "#b9900a", cursor: "pointer" }}
              onClick={() => updateStatus("Pending")}
            />
          </Tooltip>

          <Tooltip title="Ongoing">
            <SyncOutlined
              style={{ fontSize: 28, color: "#1677ff", cursor: "pointer" }}
              onClick={() => updateStatus("Ongoing")}
            />
          </Tooltip>

          <Tooltip title="Done">
            <CheckCircleOutlined
              style={{ fontSize: 28, color: "#52c41a", cursor: "pointer" }}
              onClick={() => updateStatus("Done")}
            />
          </Tooltip>

          <Tooltip title="Decline">
            <MinusCircleOutlined
              style={{ fontSize: 28, color: "#707070", cursor: "pointer" }}
              onClick={() => updateStatus("Decline")}
            />
          </Tooltip>
        </div>

        {/* ⭐ 只有有模板时才显示 WorkFlow 图 */}
        {!taskNotFound && (
          <WorkFlow
            taskId={taskId}
            projectName={projectName}
            user={user}
            inputs={taskInputs}
            outputs={taskOutputs}
            operation={taskOperation}
            operationLabel={
              taskOperation?.operation_name || "Manual Operation"
            }
            onOperationClick={() => {
              if (!taskOperation) {
                message.warning("This task requires manual operation.");
                return;
              }

              // 下面的内容需要按照 Operation 的 type 进行处理
              const { operation_name, operation_detail } = taskOperation;
              let { type } = operation_detail;
              //这里增加了弹窗提示等待功能！！！
              // 显示加载弹窗，并告知用户操作已开始
              setLoadingText(`正在执行: ${operation_name}，请稍候...`);
              setLoadingModalOpen(true);

              void (async () => {
                try {
                  switch(type) {
                    case "httpWithParameter":
                      await handleHttpWithParameter(operation_detail);
                      break;
                    case "httpWithoutParameter":
                      break;
                    default:
                      break;
                  }
                } catch (error) {
                  // 捕获上面抛出的自定义错误或网络错误
                  console.error("操作失败:", error);
                  // 向用户显示更具体的错误信息
                  messageApi.error(error.message || "操作失败，请查看控制台获取详情。");
                } finally {
                  // 确保无论成功或失败，都关闭加载弹窗
                  setLoadingModalOpen(false);
                }
              })();
            }}
          />
        )}
      </Card>

      {/* 评论区域永远显示 */}
      <Divider />

      <Card size="small" style={{ marginTop: 12, background: "#fafafa" }}>
        <Input.TextArea
          rows={4}
          placeholder="Add your comment..."
          value={currentTask.comment || ""}
          onChange={(e) =>
            setCurrentTask({
              ...currentTask,
              comment: e.target.value,
            })
          }
        />
        <Button
          type="primary"
          style={{ marginTop: 12 }}
          onClick={async () => {
            const updated = JSON.parse(JSON.stringify(projectWorkFlow));
            const task = findTaskNodeById(updated.taskTree, taskId);

            task.comment = currentTask.comment;

            const res = await updateWorkFlow({
              username: user.username,
              department: user.department,
              workflow: updated,
              projectId: Number(projectId),
            });

            res.success
              ? messageApi.success("Comment saved!")
              : messageApi.error("Save failed");
          }}
        >
          Save Comment
        </Button>
      </Card>

      {/* Edit Task Modal */}
      <Modal
        title="Edit Task Name"
        open={editModalOpen}
        onOk={updateTaskName}
        onCancel={() => setEditModalOpen(false)}
        okText="Save"
      >
        <Form layout="vertical">
          <Form.Item label="Task Name">
            <Input
              value={newTaskName}
              placeholder="Enter new task name"
              onChange={(e) => setNewTaskName(e.target.value)}
              onBlur={(e) =>
                setNewTaskName(e.target.value.replace(ILLEGAL_REGEX, ""))
              }
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 操作执行中等待弹窗 */}
      <Modal
        title="请稍候"
        open={loadingModalOpen}
        footer={null}
        closable={false}
        maskClosable={false}
        centered
      >
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <Spin size="large" />
          <p style={{ marginTop: 16, marginBottom: 0, fontSize: 15 }}>
            {loadingText}
          </p>
        </div>
      </Modal>
    </div>
  );
}
